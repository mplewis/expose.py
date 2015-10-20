from expose import Config, target_dir, hash_path_for_file

import sure  # noqa


config = Config(
    SRC_DIR='/tmp',
    DST_DIR='output',
    IMAGE_PATTERNS=('*.jpg',),
    VIDEO_PATTERNS=('*.mp4',),
    RESOLUTIONS=(3840, 2560, 1920, 1280, 1024, 640),
    VIDEO_BITRATES=(40, 24, 12, 7, 4, 2),
    VIDEO_FORMATS=('h264', 'webm'),
    VIDEO_VBR_MAX_RATIO=2,
)


def test_target_dir():
    expected = (
        ('/usr/local/bin/my_file.jpg', 'output/my_file'),
        ('/usr/local/bin/002 some file.jpg', 'output/002-some-file'),
        ('/usr/local/bin/another_new file.jpg', 'output/another_new-file'),
    )
    for in_fn, out_dir in expected:
        target_dir(config, in_fn).should.equal(out_dir)


def test_hash_path_for_file():
    (hash_path_for_file('/usr/local/bin/my_file.txt')
     .should.equal('/usr/local/bin/.my_file.txt.src.sha256'))
