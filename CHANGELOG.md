# Changelog

## 5.0.3 (unreleased)

### ✨ Improved

* Run `black` and `isort` in all the code.
* `logdir` option in actor configuration file now can contain environment variables.

### 🔧 Fixed

* Correctly subclass from `Exception` in `ICCExpections.py`.
* Fixed some regresions in the `ICC` class.


## 5.0.2 (2021-08-12)

### 🔧 Fixed

* Packaging was not including subdirectories in `actorcore`.


## 5.0.1 (2021-08-12)

### ✨ Improved

* Use `sdsstools` to define `__version__`.

### 🔧 Fixed

* Use bytes for EOF delimiters in Twisted subclasses.


## 5.0.0 (2021-08-12)

### 🚀 New

* Modify to work with Python 3 (only). Removed SVN tools. Refactored FITS tools to work with `astropy`.
