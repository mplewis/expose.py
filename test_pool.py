from pool import Config, target_dir

import sure  # noqa


config = Config(
    SRC_DIR='/tmp',
    DST_DIR='output',
    SRC_PATTERN='*.jpg',
    RESOLUTIONS=[3840, 2560, 1920, 1280, 1024, 640]
)


def test_target_dir():
    expected = (
        ('/usr/local/bin/my_file.jpg', 'output/my_file'),
        ('/usr/local/bin/002 some file.jpg', 'output/002-some-file'),
        ('/usr/local/bin/another_new file.jpg', 'output/another_new-file'),
    )
    for in_fn, out_dir in expected:
        target_dir(config, in_fn).should.equal(out_dir)
