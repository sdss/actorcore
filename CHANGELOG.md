# Changelog

## Next release

### ⚙️ Engineering

* Replace use of deprecated `imp` with `importlib`.
* Require Python 3.9 or higher.


## 5.0.5 (2021-12-08)

### 🔧 Fixed

* In FITS module, check if pvt variable is tuple instead of PVT object.


## 5.0.4 (2021-10-07)

### 🔧 Fixed

* Write bytes to the tron connection.
* Prevent FITS routines crashing if SOP or guider are not present.


## 5.0.3 (2021-09-07)

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


## v4_1_8 (2019-10-09)

### 🚀 New

* Some keys for MaStar testing in `sopActor`.
* Test keys for the `MaNGA Globular` survey mode.
* `guider_decenter` bypass to `TestHelper`.

Fixed

* Use full path when attaching controllers in an ICC.


## v4_1_7 (2018-09-23)

### 🚀 New

* Some test dictionaries for MaNGA short exposures.

Fixed

* Fix `_determine_location` that failed for `sdss4-apogee` at LCO because `'apo'` is in `'apogee'`


## v4_1_6 (2017-12-20)

### 🚀 New

* Added `productDir` to `ICC`.


## v4_1_5 (2017-12-20)

### 🚀 New

* Added `lcoGcameraICC`.


## v4_1_4 (2017-12-20)

### 🚀 New

* Added `lcoSopActor` to the `stageManager` list.


## v4_1_3 (2017-12-19)

### 🚀 New

* Added `lcoGuiderActor` to the `stageManager` list.
* Added handling of actor version from the `Actor.version` attribute.
* Added option to specify the product directory when initialising the actor.


## v4_1_2 (2017-12-17)

### 🔧 Fixed

* Fixed a bug in the new version of `stageManager` that would fail reading comments from the configuration file.


## v4_1_1 (2017-11-06)

### 🔧 Fixed

* In SDSSActor.startThreads(), the queues were being started without the thread name for SOP, which caused much pain and confusion.


## v4_1 (2017-06-11)

### 🚀 New

* Ticket #1421: Keyword parser does not accept extra values. This require version v2_5 of opscore.
* TestHelper states for MaStar survey mode and BOSS legible.
* LCO TCC cards and other header fixes in `utility.fits`.
* Refactored StageManager as a Python package and importable class object.
* Fixed TestHelper to correctly point to location specific config files.
* Added runOn and runOnCount to TestHelper.  This allows insertion of functions to run on a given command.
