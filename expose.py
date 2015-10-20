"""
expose.py
process photos and videos into a static site photojournal
https://github.com/mplewis/expose.py

Usage:
    expose.py [--dry-run] [(-v | --verbose)]
    expose.py --version

Options:
    -h --help     Show this screen.
    --version     Show version.
    --dry-run     Don't process any files, just list them.
    -v --verbose  Enable verbose log messages
"""
VERSION = 'expose.py 0.0.1'

import pyprind
from docopt import docopt

import hashlib
import json
import logging as l
from multiprocessing import Pool
from os import getcwd, makedirs
from os.path import join, basename, splitext, isfile, split
from glob import glob
from subprocess import check_call, check_output
from collections import namedtuple


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


def ffmpeg_video_cmd(cfg, src, dst, fmt, resolution, bitrate):
    options = dict(
        src=src,
        dst=dst,
        resolution=resolution,
        bitrate=bitrate,
        max_bitrate=bitrate * cfg.VIDEO_VBR_MAX_RATIO,
        threads=2,
        h264_encode_speed='medium',
    )
    return VIDEO_FMT_COMMANDS[fmt].format(**options)


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


def mkdir_for_dst(dst):
    out_dir, _ = split(dst)
    makedirs(out_dir, exist_ok=True)


def convert_image(src, dst, size):
    mkdir_for_dst(dst)
    print(sanitary_name(dst))
    check_call(['convert', src,
                '-resize', '{}x{}>'.format(size, size),
                dst])
    write_hash(src, dst)


def convert_video(cfg, src, dst, fmt, resolution, bitrate):
    mkdir_for_dst(dst)
    print(sanitary_name(dst))
    check_call(ffmpeg_video_cmd(cfg, src, dst, fmt, resolution, bitrate),
               shell=True)
    write_hash(src, dst)


def convert_image_wrap(args_array):
    convert_image(*args_array)


def convert_video_wrap(args_array):
    convert_video(*args_array)


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


def file_targets(cfg, src, is_video):
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
                    targets.append((cfg, src, dst, fmt, resolution, bitrate))
                else:
                    l.debug('Skipping {} @ {}: file exists and is cached'
                            .format(name, resolution))
                    skipped += 1
    else:
        longest = max(width, height)
        for resolution in cfg.RESOLUTIONS:
            if resolution > longest:
                l.debug('Skipping {} @ {}: longest side {} < target resolution'
                        .format(name, resolution, longest))
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
                targets.append((src, dst, resolution))
            else:
                l.debug('Skipping {} @ {}: file exists and is cached'
                        .format(name, resolution))
                skipped += 1
    return targets, skipped


def img_targets(cfg, src):
    return file_targets(cfg, src, False)


def vid_targets(cfg, src):
    return file_targets(cfg, src, True)


def img_jobs(cfg):
    l.info('Generating image jobs...')
    jobs = []
    skipped = 0
    for src in pyprind.prog_bar(src_images(cfg)):
        j, s = img_targets(cfg, src)
        jobs.extend(j)
        skipped += s
    l.info('Image jobs: running {}, skipped {}, total {}'
           .format(len(jobs), skipped, len(jobs) + skipped))
    return jobs


def vid_jobs(cfg):
    l.info('Generating video jobs...')
    jobs = []
    skipped = 0
    for src in pyprind.prog_bar(src_videos(cfg)):
        j, s = vid_targets(cfg, src)
        jobs.extend(j)
        skipped += s
    l.info('Video jobs: running {}, skipped {}, total {}'
           .format(len(jobs), skipped, len(jobs) + skipped))
    return jobs


def run_img_jobs(cfg):
    with Pool() as pool:
        pool.map(convert_image_wrap, img_jobs(cfg))


def run_vid_jobs(cfg):
    with Pool() as pool:
        pool.map(convert_video_wrap, vid_jobs(cfg))


if __name__ == '__main__':

    args = docopt(__doc__, version=VERSION)

    config = Config(
        SRC_DIR=('/Users/mplewis/Dropbox (Personal)/projectsync/'
                 'images/BWCA 2015'),
        DST_DIR=join(getcwd(), 'output'),
        IMAGE_PATTERNS=('*.jpg',),
        VIDEO_PATTERNS=('*.mp4',),
        RESOLUTIONS=(3840, 2560, 1920, 1280, 1024, 640),
        VIDEO_BITRATES=(40, 24, 12, 7, 4, 2),
        VIDEO_FORMATS=('h264', 'webm'),
        VIDEO_VBR_MAX_RATIO=2,
    )

    log_level = l.INFO
    if args['--verbose']:
        log_level = l.DEBUG

    l.basicConfig(format='%(message)s', level=log_level)

    if args['--dry-run']:
        ij = img_jobs(config)
        vj = vid_jobs(config)
        for job in ij:
            print(sanitary_name(job[1]))
        for job in vj:
            print(sanitary_name(job[2]))

    else:
        run_img_jobs(config)
        run_vid_jobs(config)
