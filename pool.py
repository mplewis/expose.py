import hashlib
from multiprocessing import Pool
from os import getcwd, makedirs
from os.path import join, basename, splitext, isfile, split
from glob import glob
from subprocess import check_call
from collections import namedtuple


Config = namedtuple('Config', 'SRC_DIR DST_DIR SRC_PATTERN RESOLUTIONS')


def src_files(cfg):
    return glob(join(cfg.SRC_DIR, cfg.SRC_PATTERN))[:3]


def convert_image(src, dst, size):
    print(sanitary_name(dst))
    out_dir, _ = split(dst)
    makedirs(out_dir, exist_ok=True)
    check_call(['convert', src, '-resize', '{}x{}>'.format(size, size), dst])


def convert_image_wrap(args_array):
    convert_image(*args_array)


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


def file_res_targets(cfg, src):
    targets = []
    name, ext = sanitary_name_and_ext(src)
    dirty = src_is_dirty(cfg, src)
    for res in cfg.RESOLUTIONS:
        full = name + '-' + str(res) + ext
        dst = join(cfg.DST_DIR, target_dir(cfg, src), full)
        if dirty or (not isfile(dst)):
            targets.append((src, dst, res))
    return targets


def gen_jobs(cfg):
    jobs = []
    for src in src_files(config):
        jobs.extend(file_res_targets(cfg, src))
    return jobs


def run_jobs(jobs):
    with Pool() as pool:
        pool.map(convert_image_wrap, jobs)


def write_hashes(cfg):
    for src in src_files(cfg):
        with open(hash_path_for_file(cfg, src), 'w') as f:
            f.write(hash_file(src))


if __name__ == '__main__':

    config = Config(
        SRC_DIR=('/Users/mplewis/Dropbox (Personal)/projectsync/'
                 'images/BWCA 2015'),
        DST_DIR=join(getcwd(), 'output'),
        SRC_PATTERN='*.jpg',
        RESOLUTIONS=[3840, 2560, 1920, 1280, 1024, 640]
    )

    run_jobs(gen_jobs(config))
    write_hashes(config)
