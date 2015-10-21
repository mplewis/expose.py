#!/usr/bin/env python3
"""
expose.py
process photos and videos into a static site photojournal
https://github.com/mplewis/expose.py

Usage:
    expose.py [(-d | --dry-run)] [(-v | --verbose)]
    expose.py (-h | --help)
    expose.py --version
    expose.py --paths

Options:
    -h --help     Show this screen
    --version     Show version
    --paths       Show script and working directories
    -d --dry-run  Don't process any files, just list them
    -v --verbose  Enable verbose log messages
"""
VERSION = 'expose.py 0.0.1'

import pyprind
from docopt import docopt
from jinja2 import Environment, FileSystemLoader

import hashlib
import json
import logging as l
from multiprocessing import Pool, Manager
from os import getcwd, makedirs
from os.path import join, basename, splitext, isfile, split, dirname, realpath
from glob import glob
from subprocess import check_call, check_output
from collections import namedtuple
from sys import exit

SCRIPT_DIR = dirname(realpath(__file__))
TEMPLATE_DIR = join(SCRIPT_DIR, 'themes')

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

VIDEO_FMT_EXTS = {
    'h264': '.mp4',
    'webm': '.webm'
}


Config = namedtuple('Config', ('SRC_DIR '
                               'DST_DIR '
                               'IMAGE_PATTERNS '
                               'VIDEO_PATTERNS '
                               'RESOLUTIONS '
                               'VIDEO_FORMATS '
                               'VIDEO_BITRATES '
                               'VIDEO_VBR_MAX_RATIO'))

ImageJob = namedtuple('ImageJob', ('src dst size dry_run'))
VideoJob = namedtuple('VideoJob', ('cfg src dst format resolution bitrate '
                                   'dry_run'))


def src_images(cfg):
    images = []
    for pattern in cfg.IMAGE_PATTERNS:
        images.extend(glob(join(cfg.SRC_DIR, pattern)))
    return images


def src_videos(cfg):
    videos = []
    for pattern in cfg.VIDEO_PATTERNS:
        videos.extend(glob(join(cfg.SRC_DIR, pattern)))
    return videos


def src_files(cfg):
    return src_images(cfg) + src_videos(cfg)


def mkdir_for_dst(dst, dry_run):
    out_dir, _ = split(dst)
    if dry_run:
        l.info('Dry run: makedirs {}'.format(out_dir))
    else:
        makedirs(out_dir, exist_ok=True)


def convert_image(job):
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
        write_hash(job.src, job.dst)


def convert_image_wrap(queue_and_job):
    queue, job = queue_and_job
    convert_image(job)
    queue.put(True)


def convert_video_wrap(queue_and_job):
    queue, job = queue_and_job
    l.debug(job)
    convert_video(job)
    queue.put(True)


def sanitary_name(src):
    name, _ = splitext(basename(src))
    return '-'.join(name.split())


def sanitary_name_and_ext(src):
    name, ext = splitext(basename(src))
    return '-'.join(name.split()), ext


def target_dir(cfg, src):
    return join(cfg.DST_DIR, sanitary_name(src))


def dimensions(src):
    cmd = ('ffprobe -v error -show_entries stream=width,height '
           '-of default=noprint_wrappers=1 -of json "{}"'
           .format(src))
    data = json.loads(check_output(cmd, shell=True).decode())['streams'][0]
    return data['width'], data['height']


# http://stackoverflow.com/a/3431838/254187
def hash_file(src):
    hash = hashlib.sha256()
    with open(src, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash.update(chunk)
    return hash.hexdigest()


def write_hash(src, dst):
    with open(hash_path_for_dst(dst), 'w') as f:
        f.write(hash_file(src))


def hash_path_for_dst(dst):
    path, name = split(dst)
    return join(path, '.' + name + '.src.sha256')


def is_dirty(src, dst):
    try:
        with open(hash_path_for_dst(dst)) as f:
            existing_hash = f.read()
    except FileNotFoundError:
        return True
    return hash_file(src) != existing_hash


def file_targets(cfg, src, is_video, dry_run):
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
                full = name + '-' + str(bitrate) + ext
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
    return file_targets(cfg, src, False, dry_run)


def vid_targets(cfg, src, dry_run):
    return file_targets(cfg, src, True, dry_run)


def media_jobs(cfg, dry_run, is_video):
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
    return media_jobs(cfg, dry_run, False)


def vid_jobs(cfg, dry_run):
    return media_jobs(cfg, dry_run, True)


def run_jobs(jobs, is_video):
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
    run_jobs(jobs, False)


def run_vid_jobs(jobs):
    run_jobs(jobs, True)


if __name__ == '__main__':

    args = docopt(__doc__, version=VERSION)

    log_level = l.INFO
    if args['--verbose']:
        log_level = l.DEBUG
    l.basicConfig(format='%(message)s', level=log_level)

    if args['--paths']:
        l.info('Working directory:   {}'.format(getcwd()))
        l.info('expose.py directory: {}'.format(SCRIPT_DIR))
        l.info('Template directory:  {}'.format(TEMPLATE_DIR))
        exit(0)

    config = Config(
        SRC_DIR=getcwd(),
        DST_DIR=join(getcwd(), '_site'),
        IMAGE_PATTERNS=['*.jpg'],
        VIDEO_PATTERNS=['*.mp4'],
        RESOLUTIONS=[3840, 2560, 1920, 1280, 1024, 640],
        VIDEO_BITRATES=[40, 24, 12, 7, 4, 2],
        VIDEO_FORMATS=['h264', 'webm'],
        VIDEO_VBR_MAX_RATIO=2,
    )

    dry_run = args['--dry-run']
    ij = img_jobs(config, dry_run)
    vj = vid_jobs(config, dry_run)
    run_img_jobs(ij)
    run_vid_jobs(vj)
