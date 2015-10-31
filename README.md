# expose.py

A static site generator for photo diaries, inspired by [Expose](https://github.com/Jack000/Expose).

# Why?

I like what Expose does. But encoding photos and videos takes a long time, and Expose doesn't support:

* Caching
* Multiprocessing
* Skipping rendering altogether and generating HTML
* Dry runs

So I rebuilt the parts of Expose I liked and added features I needed.

# Usage

```sh
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
```

# Contributions

If you built a theme for expose.py, share it with me and I'll add it to this repository!

Bug reports, fixes, or features? Feel free to open an issue or pull request any time. You can also email me at [matt@mplewis.com](mailto:matt@mplewis.com).

## Thanks to

* [tlvince](https://github.com/tlvince): great code cleanup and feature implementations :sunflower:

# License

Copyright (c) 2015 Matthew Lewis. Licensed under [the MIT License](http://opensource.org/licenses/MIT).

# To Do

## Code

* Docstrings. Docstrings everywhere
* Move JS deps into the app instead of running off cdnjs

## Docs

* Screenshots
* Contributions
* More in-depth usage
* `LICENSE`
* YAML format docs
* Template
* Styling by slide
* Examples
* Weaknesses
* How it works
