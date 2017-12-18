.. _actorcore-changelog:

==========
Change Log
==========

This document records the main changes to the actorcore code.


.. _changelog-v4_1_2:
v4_1_2 (2017-12-17)
-------------------

Fixed
^^^^^

* Fixed a bug in the new version of ``stageManager`` that would fail reading comments from the configuration file.


.. _changelog-v4_1_1:
v4_1_1 (2017-11-06)
-------------------

Fixed
^^^^^

* In SDSSActor.startThreads(), the queues were being started without the
thread name for SOP, which caused much pain and confusion.


.. _changelog-v4_1:
v4_1 (2017-06-11)
-----------------

Added
^^^^^
* Ticket #1421: Keyword parser does not accept extra values. This require version v2_5 of opscore.
* TestHelper states for MaStar survey mode and BOSS legible.
* LCO TCC cards and other header fixes in ``utility.fits``.
* Refactored StageManager as a Python package and importable class object.
* Fixed TestHelper to correctly point to location spefic config files.
* Added runOn and runOnCount to TestHelper.  This allows insertion of functions to run on a given command.

.. x.y.z (unreleased)
.. ------------------
..
.. A short description
..
.. Added
.. ^^^^^
.. * TBD
..
.. Changed
.. ^^^^^^^
.. * TBD
..
.. Fixed
.. ^^^^^
.. * TBD
