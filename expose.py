#!/usr/bin/env python3
"""
expose.py
process photos and videos into a static site photojournal
https://github.com/mplewis/expose.py

Usage:
    expose.py [--verbose --dry-run --site-only]
    expose.py [--dry-run] --create-template
    expose.py --help
    expose.py --version
    expose.py --paths

Options:
    -h, --help             Show this screen
    --version              Show version
    --paths                Show script and working directories
    -v, --verbose          Enable verbose log messages
    -d, --dry-run          Log all actions but don't execute them
    -s, --site-only        Skip rendering and just build HTML
    -c, --create-template  Create a blank metadata.yml for source files
"""
VERSION = 'expose.py 0.0.1'

# External deps
import pyprind
from docopt import docopt
from jinja2 import Environment, FileSystemLoader

# System deps
import hashlib
import json
import yaml
import re
import logging as l
from multiprocessing import Pool, Manager
from os import getcwd, makedirs
from os.path import (join, basename, splitext, isfile, split, dirname,
                     realpath, isdir)
from glob import glob
from subprocess import check_call, check_output
from collections import (namedtuple, OrderedDict)
from sys import exit
from shutil import copy

# Templates are relative to the script, not the source directory
SCRIPT_DIR = dirname(realpath(__file__))
TEMPLATES_DIR = join(SCRIPT_DIR, 'templates')

# The FFmpeg commands used to convert a source video into a given format.
# Video conversion is a lot trickier than image conversion.
VIDEO_FMT_COMMANDS = {
    'h264': (
        'ffmpeg '
        '-loglevel error '
        '-y '
        '-i "{src}" '
        '-c:v libx264 '
        '-threads {threads} '
        '-vf scale="{resolution}:trunc(ow/a/2)*2" '
        '-profile:v high '
        '-pix_fmt yuv420p '
        '-preset {h264_encode_speed} '
        '-b:v {bitrate}M '
        '-maxrate {max_bitrate}M '
        '-bufsize {max_bitrate}M '
        '-movflags +faststart '
        '-f mp4 '
        '"{dst}"'
    ),
    'webm': (
        'ffmpeg '
        '-loglevel error '
        '-y '
        '-i "{src}" '
        '-c:v libvpx '
        '-threads {threads} '
        '-vf scale="{resolution}:trunc(ow/a/2)*2" '
        '-pix_fmt yuv420p '
        '-b:v {bitrate}M '
        '-maxrate {max_bitrate}M '
        '-bufsize {max_bitrate}M '
        '-f webm '
        '"{dst}"'
    ),
}

# The extensions that go with each video format. Don't forget the dot.
VIDEO_FMT_EXTS = {
    'h264': '.mp4',
    'webm': '.webm'
}

METADATA_FILENAME = 'metadata.yml'

# Config is a named tuple that's passed between most of these methods. It
# makes it easier to work with a runtime config without making the config a
# global.
Config = namedtuple('Config', ('SRC_DIR '
                               'DST_DIR '
                               'TEMPLATE '
                               'IMAGE_PATTERNS '
                               'VIDEO_PATTERNS '
                               'RESOLUTIONS '
                               'VIDEO_FORMATS '
                               'VIDEO_BITRATES '
                               'VIDEO_VBR_MAX_RATIO'))

# ImageJob and VideoJob are named tuples that hold info on a single image/video
# output target job. They're easy to pass around multithreading pools.
ImageJob = namedtuple('ImageJob', ('src dst size dry_run'))
VideoJob = namedtuple('VideoJob', ('cfg src dst format resolution bitrate '
                                   'dry_run'))


class WebMediaSlice:
    """
    A slice is a single processed file that makes up part of the output for
    a given source media file.

    For example, if canoe-trip.mp4 was the source file, you might see slices
    like canoe-trip-640.mp4 and canoe-trip-1080.mp4.
    """
    def __init__(self, source):
        """Create a WebMediaSlice from a full path to an output file."""
        self.source = source
        # Grab the width off the filename: *-WIDTH.*
        _, self.name = split(source)
        self.width = int(re.match(r'^.+-(\d+)\..+$', source).groups()[0])

    def __repr__(self):
        media_type = 'image'
        if self.is_video:
            media_type = 'video'
        return '<WebMediaSlice: {}w ({})>'.format(self.width, media_type)

    @property
    def is_video(self):
        """True if this is a video file, False otherwise"""
        return not self.source.endswith('.jpg')


class WebMedia:
    """A bundle of WebMediaSlices that corresponds to an input file."""
    def __init__(self, directory, sources):
        """Create a WebMedia object from a set of output files."""
        self.directory = directory
        _, self.name = split(directory)
        self.slices = [WebMediaSlice(source) for source in sources]

    def __repr__(self):
        media_type = 'image'
        if self.is_video:
            media_type = 'video'
        return '<WebMedia: {} ({})>'.format(self.name, media_type)

    @property
    def is_video(self):
        """True if any slice is a video file, False otherwise"""
        for s in self.slices:
            if s.is_video:
                return True
        return False


def src_images(cfg):
    """List the paths to source images."""
    images = []
    for pattern in cfg.IMAGE_PATTERNS:
        images.extend(glob(join(cfg.SRC_DIR, pattern)))
    return images


def src_videos(cfg):
    """List the paths to source videos."""
    videos = []
    for pattern in cfg.VIDEO_PATTERNS:
        videos.extend(glob(join(cfg.SRC_DIR, pattern)))
    return videos


def mkdir_for_dst(dst, dry_run):
    """Create a directory to the given path and all necessary parents."""
    out_dir, _ = split(dst)
    if dry_run:
        l.info('Dry run: makedirs {}'.format(out_dir))
    else:
        makedirs(out_dir, exist_ok=True)


def convert_image(job):
    """Convert a single output image designated by an ImageJob."""
    mkdir_for_dst(job.dst, dry_run)
    cmd = ['convert', job.src,
           '-resize', '{}x>'.format(job.size),
           job.dst]
    if job.dry_run:
        l.info('Dry run: {}'.format(' '.join(cmd)))
    else:
        check_call(cmd)
        write_hash(job.src, job.dst)


def convert_video(job):
    """Convert a single output video designated by a VideoJob."""

    # First create the output video
    mkdir_for_dst(job.dst, dry_run)
    options = dict(
        src=job.src,
        dst=job.dst,
        resolution=job.resolution,
        bitrate=job.bitrate,
        max_bitrate=job.bitrate * job.cfg.VIDEO_VBR_MAX_RATIO,
        threads=2,
        h264_encode_speed='medium',
    )
    cmd_template = VIDEO_FMT_COMMANDS[job.format]
    cmd = cmd_template.format(**options)
    if job.dry_run:
        l.info('Dry run: {}'.format(cmd))
    else:
        check_call(cmd, shell=True)

    # Then create the cover image
    name, ext = splitext(job.dst)
    poster_dst = name + '.jpg'

    # One of the other video targets may have already made the poster for this
    # video resolution
    if not isfile(poster_dst):
        cmd = ('ffmpeg -loglevel error -i "{}" -vframes 1 -f image2 "{}"'
               .format(job.dst, poster_dst))
        if job.dry_run:
            l.info('Dry run: {}'.format(cmd))
        else:
            check_call(cmd, shell=True)

    if not job.dry_run:
        # Hash only gets written when the video and its poster image are done
        write_hash(job.src, job.dst)


def convert_image_wrap(queue_and_job):
    """Wrapper to support multiprocessing ImageJobs with a progress queue."""
    queue, job = queue_and_job
    convert_image(job)
    queue.put(True)


def convert_video_wrap(queue_and_job):
    """Wrapper to support multiprocessing VideoJobs with a progress queue."""
    queue, job = queue_and_job
    l.debug(job)
    convert_video(job)
    queue.put(True)


def sanitary_name(src):
    """
    Sanitize a name for conversion. Replace whitespace with hyphens.
    Returns basename ONLY.
    """
    name, _ = sanitary_name_and_ext(src)
    return name


def sanitary_name_and_ext(src):
    """
    Sanitize a name for conversion. Replace whitespace with hyphens.
    Returns basename, extension.
    """
    name, ext = splitext(basename(src))
    return '-'.join(name.split()), ext


def target_dir(cfg, src):
    """Get the target directory path for a source media file."""
    return join(cfg.DST_DIR, sanitary_name(src))


def dimensions(src):
    """Get the dimensions of a video or image. (Works with images!!)"""
    cmd = ('ffprobe -v error -show_entries stream=width,height '
           '-of default=noprint_wrappers=1 -of json "{}"'
           .format(src))
    data = json.loads(check_output(cmd, shell=True).decode())['streams'][0]
    return data['width'], data['height']


# http://stackoverflow.com/a/3431838/254187
def hash_file(src):
    """SHA-256 a file and return the ASCII hex hash."""
    hash = hashlib.sha256()
    with open(src, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash.update(chunk)
    return hash.hexdigest()


def write_hash(src, dst):
    """Write the hash of a source file to the path specified."""
    with open(hash_path_for_dst(dst), 'w') as f:
        f.write(hash_file(src))


def hash_path_for_dst(dst):
    """Get the path of a hash file for a given output file."""
    path, name = split(dst)
    return join(path, '.' + name + '.src.sha256')


def is_dirty(src, dst):
    """
    True if the destination file is up-to-date with the source file.
    False if the destination file doesn't exist, the destination hash doesn't
    exist, or the source file has changed since the hash was last generated.
    """
    try:
        with open(hash_path_for_dst(dst)) as f:
            existing_hash = f.read()
    except FileNotFoundError:
        return True
    return hash_file(src) != existing_hash


# Major refactor target. This is too big.
# Confusing naming between x_targets and x_jobs.
def file_targets(cfg, src, is_video, dry_run):
    """
    Generate jobs for a single source media file.
    Returns a list of jobs for this source file, and the number of jobs
    skipped due to caching.

    This method doesn't know what format the source file is - make sure to set
    is_video properly based on the source file format.
    """
    targets = []
    skipped = 0
    name, ext = sanitary_name_and_ext(src)
    width, height = dimensions(src)
    if is_video:
        for fmt in cfg.VIDEO_FORMATS:
            ext = VIDEO_FMT_EXTS[fmt]
            for i, resolution in enumerate(cfg.RESOLUTIONS):
                if resolution > width:
                    l.debug('Skipping {} @ {}: width {} < target resolution'
                            .format(name, resolution, width))
                    continue
                bitrate = cfg.VIDEO_BITRATES[i]
                full = name + '-' + str(resolution) + ext
                dst = join(cfg.DST_DIR, target_dir(cfg, src), full)
                if (not isfile(dst)) or is_dirty(src, dst):
                    if not isfile(dst):
                        reason = 'does not exist'
                    else:
                        reason = 'dirty'
                    l.debug('Added target: {} @ {}px/{}M ({})'
                            .format(name, resolution, bitrate, reason))
                    job = VideoJob(cfg, src, dst, fmt, resolution, bitrate,
                                   dry_run)
                    targets.append(job)
                else:
                    l.debug('Skipping {} @ {}: file exists and is cached'
                            .format(name, resolution))
                    skipped += 1
    else:
        for resolution in cfg.RESOLUTIONS:
            if resolution > width:
                l.debug('Skipping {} @ {}: width {} < target resolution'
                        .format(name, resolution, width))
                continue
            full = name + '-' + str(resolution) + ext
            dst = join(cfg.DST_DIR, target_dir(cfg, src), full)
            if (not isfile(dst)) or is_dirty(src, dst):
                if not isfile(dst):
                    reason = 'does not exist'
                else:
                    reason = 'dirty'
                l.debug('Added target: {} @ {}px ({})'
                        .format(name, resolution, reason))
                job = ImageJob(src, dst, resolution, dry_run)
                targets.append(job)
            else:
                l.debug('Skipping {} @ {}: file exists and is cached'
                        .format(name, resolution))
                skipped += 1
    return targets, skipped


def img_targets(cfg, src, dry_run):
    """
    Generate image jobs for a single source image file.
    Returns a list of jobs for this source file, and the number of jobs
    skipped due to caching.

    This method only works on image sources.
    """
    return file_targets(cfg, src, False, dry_run)


def vid_targets(cfg, src, dry_run):
    """
    Generate video jobs for a single source video file.
    Returns a list of jobs for this source file, and the number of jobs
    skipped due to caching.

    This method only works on video sources.
    """
    return file_targets(cfg, src, True, dry_run)


def media_jobs(cfg, dry_run, is_video):
    """Generate either all image or all video jobs for a given config."""
    if is_video:
        media_lc = 'video'
        media_uc = 'Video'
        src_media = src_videos
        media_targets = vid_targets
    else:
        media_lc = 'image'
        media_uc = 'Image'
        src_media = src_images
        media_targets = img_targets

    l.info('Generating {} jobs...'.format(media_lc))
    jobs = []
    skipped = 0

    si = src_media(cfg)
    if not si:
        l.debug('No source {}s'.format(media_lc))
        return

    for src in pyprind.prog_bar(si):
        j, s = media_targets(cfg, src, dry_run)
        jobs.extend(j)
        skipped += s

    l.info('{} jobs: running {}, skipped {}, total {}'
           .format(media_uc, len(jobs), skipped, len(jobs) + skipped))

    return jobs


def img_jobs(cfg, dry_run):
    """Generate all image jobs for a given config."""
    return media_jobs(cfg, dry_run, False)


def vid_jobs(cfg, dry_run):
    """Generate all video jobs for a given config."""
    return media_jobs(cfg, dry_run, True)


def run_jobs(jobs, is_video):
    """
    Run a set of image or video jobs. This processes the media and runs all
    conversions in the jobs list.
    """
    if not jobs:
        return
    if is_video:
        wrapper = convert_video_wrap
        media_type = 'video'
    else:
        wrapper = convert_image_wrap
        media_type = 'image'
    l.info('Processing {}s...'.format(media_type))
    with Pool() as pool:
        manager = Manager()
        queue = manager.Queue()
        wrapped_jobs = [(queue, j) for j in jobs]
        total = len(wrapped_jobs)
        bar = pyprind.ProgBar(total)
        pool.map_async(wrapper, wrapped_jobs)
        while total > 0:
            queue.get()
            bar.update()
            total -= 1


def run_img_jobs(jobs):
    """
    Run a set of image jobs. This processes the media and runs all
    conversions in the jobs list.
    """
    run_jobs(jobs, False)


def run_vid_jobs(jobs):
    """
    Run a set of video jobs. This processes the media and runs all
    conversions in the jobs list.
    """
    run_jobs(jobs, True)


def web_media_from_output(rendered_dir):
    """
    Get WebMedia objects from a directory that contains directories for all
    output media.
    """
    l.info('Gathering rendered media from {}'.format(rendered_dir))
    media_globs = ['*.mp4', '*.jpg', '*.webm']
    media_dirs = glob(join(rendered_dir, '*'))

    # Filter files out - static files may be lying around from the last build
    media_dirs = [d for d in media_dirs if isdir(d)]

    all_media = []
    for mp in media_dirs:
        media_paths = []
        for ext in media_globs:
            media_paths.extend(glob(join(mp, ext)))
        wm = WebMedia(mp, media_paths)
        all_media.append(wm)
    return all_media


def template_dir(cfg):
    """Get the source directory for the template in use."""
    return join(TEMPLATES_DIR, cfg.TEMPLATE)


def render_html_from_media(cfg, media, dry_run):
    """
    Read output files and render HTML into the output directory.
    """
    l.info('Rendering HTML from {} media items'.format(len(media)))
    env = Environment(loader=FileSystemLoader(template_dir(cfg)))
    template = env.get_template('index.html.jinja2')
    rendered = template.render({'media': media})
    html_out = join(cfg.DST_DIR, 'index.html')
    if dry_run:
        l.info('Dry run: render HTML to {}'.format(html_out))
    else:
        with open(html_out, 'w') as f:
            f.write(rendered)


def copy_template_static_files(cfg, dry_run):
    """
    Copy the template's files into the output directory.
    """
    l.info('Copying static files for theme')
    static_files = [f for f in glob(join(template_dir(cfg), '*'))
                    if not f.endswith('.jinja2')]
    for f in static_files:
        if dry_run:
            l.info('Dry run: copy {} to {}'.format(f, cfg.DST_DIR))
        else:
            copy(f, cfg.DST_DIR)


# http://stackoverflow.com/a/21912744
# How does this work?
def ordered_dump(data, stream=None, Dumper=yaml.Dumper, **kwds):
    class OrderedDumper(Dumper):
        pass

    def _dict_representer(dumper, data):
        return dumper.represent_mapping(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            data.items())

    OrderedDumper.add_representer(OrderedDict, _dict_representer)
    return yaml.dump(data, stream, OrderedDumper, **kwds)


def generate_metadata_template(cfg):
    """Generate an empty YAML metadata file from the available source media."""
    slides = {'slides': {}}
    for pattern in cfg.IMAGE_PATTERNS + cfg.VIDEO_PATTERNS:
        for f in glob(pattern):
            slide = sanitary_name(f)
            slides['slides'][slide] = {
                'content': '',
                'style': ''
            }
    return ordered_dump(slides, default_flow_style=False)


def copy_metadata(cfg, dry_run):
    """
    Copy metadata from source YAML to output JSON. Create a blank template
    if none exists.
    """
    metadata = join(cfg.SRC_DIR, METADATA_FILENAME)
    if isfile(metadata):
        with open(metadata) as f:
            metadata = json.dumps(yaml.load(f))
            json_path = join(cfg.DST_DIR, 'metadata.json')
            if dry_run:
                l.info('Dry run: Writing {}'.format(json_path))
            else:
                l.info('Writing {}'.format(json_path))
                with open(json_path, 'w') as j:
                    j.write(metadata)
    else:
        l.info('No {} found'.format(METADATA_FILENAME))
        create_template(cfg, dry_run)


def create_template(cfg, dry_run):
    """
    Create a blank metadata template unless a metadata file already exists.
    """
    metadata = join(cfg.SRC_DIR, METADATA_FILENAME)

    if isfile(metadata):
        l.error('{} exists already, cowardly refusing to overwrite it.'
                .format(METADATA_FILENAME))
        l.error('If you want to create a new template from scratch, please '
                'delete the existing {}, then re-run this command.'
                .format(METADATA_FILENAME))
        return False

    if dry_run:
        l.info('Dry run: Writing metadata template to {}'.format(metadata))
    else:
        l.info('Writing metadata template to {}'.format(metadata))
        metadata_template = generate_metadata_template(cfg)
        with open(metadata, 'w') as f:
            f.write(metadata_template)
    return True


if __name__ == '__main__':

    # Parse args with the docstring using Docopt
    args = docopt(__doc__, version=VERSION)

    # Most libraries set their log level to WARN during normal use.
    # We set ours to INFO during normal use and DEBUG during --verbose.
    log_level = l.INFO
    if args['--verbose']:
        log_level = l.DEBUG
    l.basicConfig(format='%(message)s', level=log_level)

    # --paths: display paths and exit
    if args['--paths']:
        l.info('Working directory:   {}'.format(getcwd()))
        l.info('expose.py directory: {}'.format(SCRIPT_DIR))
        l.info('Template directory:  {}'.format(TEMPLATES_DIR))
        exit(0)

    # The default config.
    # No way to modify this right now besides editing this file.
    config = Config(
        SRC_DIR=getcwd(),
        DST_DIR=join(getcwd(), '_site'),
        TEMPLATE='fullwide',
        IMAGE_PATTERNS=['*.jpg'],
        VIDEO_PATTERNS=['*.mp4'],
        RESOLUTIONS=[3840, 2560, 1920, 1280, 1024, 640],
        VIDEO_BITRATES=[40, 24, 12, 7, 4, 2],
        VIDEO_FORMATS=['h264', 'webm'],
        VIDEO_VBR_MAX_RATIO=2,
    )

    # Dry run: don't write anything
    dry_run = args['--dry-run']

    # Create template: simply create a metadata.yml if it doesn't already
    # exist. If it does, throw an error and exit
    if args['--create-template']:
        l.info('Creating a new metadata template')
        if create_template(config, dry_run):
            exit(0)
        else:
            exit(1)  # couldn't create template

    # --site-only: useful for when you're tweaking your template, because
    # parsing image/video jobs can take a while
    if args['--site-only']:
        l.info('Skipping render phase')
    else:
        ij = img_jobs(config, dry_run)
        vj = vid_jobs(config, dry_run)
        run_img_jobs(ij)
        run_vid_jobs(vj)

    # These steps should be self-explanatory:
    # Read the output dir and make a list of media found
    media = web_media_from_output(config.DST_DIR)
    # Render HTML from the media we just found
    render_html_from_media(config, media, dry_run)
    # Add the template files
    copy_template_static_files(config, dry_run)
    # Copy the metadata.yml into a metadata.json
    copy_metadata(config, dry_run)
