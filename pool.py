import hashlib
from multiprocessing import Pool
from os import getcwd, makedirs
from os.path import join, basename, splitext, isfile, split
from glob import glob
from subprocess import check_call
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
    return images[:3]


def src_videos(cfg):
    videos = []
    for pattern in cfg.VIDEO_PATTERNS:
        videos.extend(glob(join(cfg.SRC_DIR, pattern)))
    return videos[:3]


def src_files(cfg):
    return src_images + src_videos


def mkdir_for_dst(dst):
    out_dir, _ = split(dst)
    makedirs(out_dir, exist_ok=True)


def convert_image(src, dst, size, quality):
    print(sanitary_name(dst))
    mkdir_for_dst(dst)
    print(src, size)
    check_call(['convert', src,
                '-resize', '{}x{}>'.format(size, size),
                dst])


def convert_video(cfg, src, dst, fmt, resolution, bitrate):
    mkdir_for_dst(dst)
    print(src, fmt, resolution)
    check_call(ffmpeg_video_cmd(cfg, src, dst, fmt, resolution, bitrate),
               shell=True)


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


# http://stackoverflow.com/a/3431838/254187
def hash_file(src):
    hash = hashlib.sha256()
    with open(src, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash.update(chunk)
    return hash.hexdigest()


def hash_path_for_file(cfg, src):
    return join(target_dir(cfg, src), '.src.sha256')


def src_is_dirty(cfg, src):
    fresh_hash = hash_file(src)
    try:
        with open(hash_path_for_file(cfg, src)) as f:
            existing_hash = f.read()
    except FileNotFoundError:
        return True
    return fresh_hash != existing_hash


def file_targets(cfg, src, is_video):
    targets = []
    name, ext = sanitary_name_and_ext(src)
    dirty = src_is_dirty(cfg, src)
    if is_video:
        for fmt in cfg.VIDEO_FORMATS:
            ext = VIDEO_FMT_EXTS[fmt]
            for i, resolution in enumerate(cfg.RESOLUTIONS):
                bitrate = cfg.VIDEO_BITRATES[i]
                full = name + '-' + str(bitrate) + ext
                dst = join(cfg.DST_DIR, target_dir(cfg, src), full)
                if dirty or (not isfile(dst)):
                    targets.append((cfg, src, dst, fmt, resolution, bitrate))
    else:
        for resolution in cfg.RESOLUTIONS:
            full = name + '-' + str(resolution) + ext
            dst = join(cfg.DST_DIR, target_dir(cfg, src), full)
            if dirty or (not isfile(dst)):
                targets.append((src, dst, resolution))
    return targets


def img_targets(cfg, src):
    return file_targets(cfg, src, False)


def vid_targets(cfg, src):
    return file_targets(cfg, src, True)


def img_jobs(cfg):
    jobs = []
    for src in src_images(cfg):
        jobs.extend(img_targets(cfg, src))
    return jobs


def vid_jobs(cfg):
    jobs = []
    for src in src_videos(cfg):
        jobs.extend(vid_targets(cfg, src))
    return jobs[:6]


def run_img_jobs(cfg):
    with Pool() as pool:
        pool.map(convert_image_wrap, img_jobs(cfg))


def run_vid_jobs(cfg):
    with Pool() as pool:
        pool.map(convert_video_wrap, vid_jobs(cfg))


def write_hashes(cfg):
    for src in src_images(cfg):
        with open(hash_path_for_file(cfg, src), 'w') as f:
            f.write(hash_file(src))


if __name__ == '__main__':

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

    run_img_jobs(config)
    run_vid_jobs(config)
    write_hashes(config)
