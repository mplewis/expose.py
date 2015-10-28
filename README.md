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
    expose.py [(-v | --verbose)] [(-d | --dry-run)] [(-s | --site-only)]
    expose.py (-h | --help)
    expose.py --version
    expose.py --paths

Options:
    -h --help       Show this screen
    --version       Show version
    --paths         Show script and working directories
    -v --verbose    Enable verbose log messages
    -d --dry-run    Log all actions but don't execute them
    -s --site-only  Skip rendering and just build HTML
```

# License

MIT

# To Do

## Docs

* Contributions
* More in-depth usage
* `LICENSE`
* YAML format docs
* Template
* Styling by slide
* Examples
* Weaknesses
