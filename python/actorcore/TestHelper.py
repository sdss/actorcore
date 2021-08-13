"""
Help for writing test cases that need a Cmdr, Model, Actor, etc.
"""

import importlib
import io
import logging
import os
import re
import sys
import threading
import time

import opscore.protocols.validation as validation
from opscore.actor import keyvar
from opscore.protocols import keys, messages, parser

from . import Actor


call_lock = threading.RLock()

# To allow fake-setting/handling of the various actor models.
globalModels = {}


def merge_dicts(*args):
    """Merge many dicts and return the result."""
    return {k: v for d in args for k, v in d.items()}


# MCP state setup
ffsClosed = {"ffsStatus": ["01"] * 8}
ffsOpen = {"ffsStatus": ["10"] * 8}
arcOn = {"hgCdLamp": ["1"] * 4, "neLamp": ["1"] * 4}
arcOff = {"hgCdLamp": ["0"] * 4, "neLamp": ["0"] * 4}
flatOn = {"ffLamp": ["1"] * 4}
flatOff = {"ffLamp": ["0"] * 4}
othersOff = {"whtLampCommandedOn": [0], "uvLampCommandedOn": [0]}
semaphoreGood = {"semaphoreOwner": ["None"]}
semaphoreBad = {"semaphoreOwner": ["SomeEvilGuy"]}
semaphoreTCC = {"semaphoreOwner": ["TCC:0:0"]}
gangBad = {"apogeeGang": [1]}
gangCart = {"apogeeGang": [2]}
gangPodium = {"apogeeGang": [4]}
gang1m = {"apogeeGang": [36]}
mcpState = {}
mcpState["flats"] = merge_dicts(ffsClosed, arcOff, flatOn, gangPodium)
mcpState["arcs"] = merge_dicts(ffsClosed, arcOn, flatOff, gangPodium)
mcpState["boss_science"] = merge_dicts(ffsOpen, arcOff, flatOff, gangPodium)
mcpState["apogee_science"] = merge_dicts(ffsOpen, arcOff, flatOff, gangCart)
mcpState["all_off"] = merge_dicts(ffsClosed, arcOff, flatOff, gangPodium)
mcpState["apogee_parked"] = merge_dicts(ffsClosed, arcOff, flatOff, gangCart)
mcpState["bad_semaphore"] = merge_dicts(ffsClosed, arcOff, flatOff, gangCart)
mcpState["tcc_semaphore"] = merge_dicts(ffsClosed, arcOff, flatOff, gangCart)

# these lamps should always be off, so set them as such...
for n in mcpState:
    mcpState[n].update(othersOff)
    mcpState[n].update(semaphoreGood)

mcpState["bad_semaphore"].update(semaphoreBad)
mcpState["tcc_semaphore"].update(semaphoreTCC)

# APOGEE state setup
ditherA = {"ditherPosition": [0, "A"]}
ditherB = {"ditherPosition": [0.5, "B"]}
ditherUnknown = {"ditherPosition": ["NaN", "?"]}
shutterClosed = {"shutterLimitSwitch": ["false", "true"]}
shutterOpen = {"shutterLimitSwitch": ["true", "false"]}
shutterUnknown = {"shutterLimitSwitch": ["false", "false"]}
notReading = {"utrReadState": ["", "Done", 0, 0]}
reading = {"utrReadState": ["object", "Reading", 1, 2]}
done = {"exposureState": ["Done", "science", 100, "APOGEE_expName"]}
exposing = {"exposureState": ["Exposing", "science", 100, "APOGEE_expName"]}
stopped = {"exposureState": ["Stopped", "science", 100, "APOGEE_expName"]}
failed = {"exposureState": ["Failed", "science", 100, "APOGEE_expName"]}
apogeeState = {}
apogeeState["A_closed"] = merge_dicts(ditherA, shutterClosed, notReading, done)
apogeeState["B_open"] = merge_dicts(ditherB, shutterOpen, notReading, done)
apogeeState["unknown"] = merge_dicts(ditherUnknown, shutterUnknown, notReading, done)
apogeeState["done"] = merge_dicts(ditherA, shutterClosed, notReading, done)
apogeeState["exposing"] = merge_dicts(ditherA, shutterOpen, notReading, exposing)

# BOSS state setup
exposureIdle = {"exposureState": ["IDLE", 0, 0]}
exposureIntegrating = {"exposureState": ["INTEGRATING", 900, 100]}
exposureReading = {"exposureState": ["READING", 60, 10]}
exposureAborted = {"exposureState": ["ABORTED", 0, 0]}
exposureLegible = {"exposureState": ["LEGIBLE", 0, 0]}
bossExposureId = {"exposureId": [1234500], "BeginExposure": [1411421207, 56922.89]}

bossState = {}
bossState["idle"] = merge_dicts(exposureIdle, bossExposureId)
bossState["integrating"] = merge_dicts(exposureIntegrating, bossExposureId)
bossState["reading"] = merge_dicts(exposureReading, bossExposureId)
bossState["aborted"] = merge_dicts(exposureAborted, bossExposureId)
bossState["legible"] = merge_dicts(exposureLegible, bossExposureId)

# TCC state setup
# NEWTCC: tccStatus is deprecated in the new TCC.
tccBase = {
    "axisBadStatusMask": ["0x00057800"],
    "utc_TAI": [-35.0],
    "moveItems": [""],
    "inst": ["guider"],
    "objName": [""],
    "slewEnd": "",
    "objNetPos": [121.0, 0.0, 4908683470.64, 30.0, 0.0, 4908683470.64],
}
tccMoving = {
    "axisBadStatusMask": ["0x00057800"],
    "utc_TAI": [-35.0],
    "moveItems": ["YYYYYYYYY"],
    "inst": ["guider"],
    "objName": [""],
    "slewEnd": "",
    "slewBeg": [4908683470.64],
    "objNetPos": [121.0, 0.0, 4908683470.64, 30.0, 0.0, 4908683470.64],
}

axisStatClear = {"azStat": [0] * 4, "altStat": [0] * 4, "rotStat": [0] * 4}
axisStatStopped = {
    "azStat": [0x2000] * 4,
    "altStat": [0x2000] * 4,
    "rotStat": [0x2000] * 4,
}
axisStatBad = {"azStat": [0x1800] * 4, "altStat": [0x1800] * 4, "rotStat": [0x1800] * 4}
axisStatBadAz = {"azStat": [0x1800] * 4, "altStat": [0x0] * 4, "rotStat": [0x0] * 4}
axisCmdState_halted = {"axisCmdState": ["Halted", "Halted", "Halted"]}
axisCmdState_azhalted = {"axisCmdState": ["Halted", "Slewing", "Slewing"]}
axisCmdState_slewing = {"axisCmdState": ["Slewing", "Slewing", "Slewing"]}
axisCmdState_tracking = {"axisCmdState": ["Tracking", "Tracking", "Tracking"]}

atStow = {"axePos": [121, 30, 0]}
atAlt15 = {"axePos": [121, 15, 0]}
atGangChange = {"axePos": [121, 45, 0]}
atInstChange = {"axePos": [0, 90, 0]}
atSomeField = {"axePos": [12, 34, 56]}
noErrorCode = {"axisErrCode": ["OK", "OK", "OK"]}
haltedErrorCode = {"axisErrCode": ["HaltRequested", "HaltRequested", "HaltRequested"]}
haltedOneErrorCode = {"axisErrCode": ["HaltRequested", "OK", "OK"]}

tccState = {}
tccState["stopped"] = merge_dicts(
    tccBase, axisStatStopped, atStow, axisCmdState_halted, noErrorCode
)
tccState["halted"] = merge_dicts(
    tccBase, axisStatClear, atGangChange, axisCmdState_halted, haltedErrorCode
)
tccState["tracking"] = merge_dicts(
    tccMoving, axisStatClear, atSomeField, axisCmdState_tracking, noErrorCode
)
tccState["slewing"] = merge_dicts(
    tccMoving, axisStatClear, atSomeField, axisCmdState_slewing, noErrorCode
)
tccState["bad"] = merge_dicts(
    tccBase, axisStatBad, atInstChange, axisCmdState_halted, haltedErrorCode
)
tccState["halted_low"] = merge_dicts(
    tccBase, axisStatBadAz, atAlt15, axisCmdState_halted, haltedOneErrorCode
)
tccState["badAz"] = merge_dicts(
    tccBase, axisStatBadAz, atStow, axisCmdState_azhalted, haltedOneErrorCode
)

# guider state setup
noneLoaded = {"cartridgeLoaded": [-1, -1, "?", -1, -1]}
bossLoaded = {
    "cartridgeLoaded": [11, 1000, "A", 54321, 1],
    "survey": ["BOSS", "None"],
    "loadedNewCartridge": [],
}
apogeeLoaded = {
    "cartridgeLoaded": [1, 2000, "A", 54321, 2],
    "survey": ["APOGEE", "None"],
    "loadedNewCartridge": [],
}
mangaDitherLoaded = {
    "cartridgeLoaded": [2, 3000, "A", 54321, 3],
    "survey": ["MaNGA", "MaNGA Dither"],
    "loadedNewCartridge": [],
}
mangaGlobularLoaded = {
    "cartridgeLoaded": [2, 3000, "A", 54321, 3],
    "survey": ["MaNGA", "MaNGA Globular"],
    "loadedNewCartridge": [],
}
manga10Loaded = {
    "cartridgeLoaded": [2, 3000, "A", 54321, 3],
    "survey": ["MaNGA", "MaNGA 10min"],
    "loadedNewCartridge": [],
}
mangaStareLoaded = {
    "cartridgeLoaded": [2, 3001, "A", 54321, 3],
    "survey": ["MaNGA", "MaNGA Stare"],
    "loadedNewCartridge": [],
}
MaStarLoaded = {
    "cartridgeLoaded": [2, 3001, "A", 54321, 3],
    "survey": ["MaNGA", "MaStar"],
    "loadedNewCartridge": [],
}
apogeemangaDitherLoaded = {
    "cartridgeLoaded": [3, 4000, "A", 54321, 4],
    "survey": ["APOGEE-2&MaNGA", "MaNGA Dither"],
    "loadedNewCartridge": [],
}
apogeemangaGlobularLoaded = {
    "cartridgeLoaded": [3, 4000, "A", 54321, 4],
    "survey": ["APOGEE-2&MaNGA", "MaNGA Globular"],
    "loadedNewCartridge": [],
}
apogeemangaStareLoaded = {
    "cartridgeLoaded": [3, 4000, "A", 54321, 4],
    "survey": ["APOGEE-2&MaNGA", "MaNGA Stare"],
    "loadedNewCartridge": [],
}
apogeemangaMaStarLoaded = {
    "cartridgeLoaded": [3, 4000, "A", 54321, 4],
    "survey": ["APOGEE-2&MaNGA", "MaStar"],
    "loadedNewCartridge": [],
}
apogeemanga10Loaded = {
    "cartridgeLoaded": [3, 4000, "A", 54321, 4],
    "survey": ["APOGEE-2&MaNGA", "MaNGA 10min"],
    "loadedNewCartridge": [],
}
apogeeLeadLoaded = {
    "cartridgeLoaded": [3, 4000, "A", 54321, 4],
    "survey": ["APOGEE-2&MaNGA", "APOGEE Lead"],
    "loadedNewCartridge": [],
}
apogeemangaLoadedNoSurveyMode = {
    "cartridgeLoaded": [3, 4000, "A", 54321, 4],
    "survey": ["APOGEE-2&MaNGA", "None"],
    "loadedNewCartridge": [],
}
noDecenter = {"decenter": [0, "disabled", 0, 0, 0, 0, 0]}
yesDecenter = {"decenter": [0, "enabled", 0, 0, 0, 0, 0]}
guiderOn = {"guideState": ["on"], "file": ["/tmp/", "proc-gimg-1234.fits.gz"]}
guiderOff = {"guideState": ["off"], "file": ["/tmp/", "proc-gimg-6789.fits.gz"]}
guiderFailed = {"guideState": ["failed"]}
guiderStopped = {"guideState": ["stopped"]}

# The below was stolen from guiderActor.Commands.GuiderCommand
mangaDithers = {
    "N": (-0.417, +0.721, 0.0),
    "S": (-0.417, -0.721, 0.0),
    "E": (+0.833, 0.000, 0.0),
    "C": (0.0, 0.0, 0.0),
}
mangaN = {"mangaDither": ["N"], "decenter": [0, "enabled", -0.417, +0.721, 0, 0, 0]}
mangaS = {"mangaDither": ["S"], "decenter": [0, "enabled", -0.417, -0.721, 0, 0, 0]}
mangaE = {"mangaDither": ["E"], "decenter": [0, "enabled", +0.833, 0, 0, 0, 0]}
mangaC = {"mangaDither": ["C"], "decenter": [0, "disabled", 0, 0, 0, 0, 0]}
mangaCenabled = {"mangaDither": ["C"], "decenter": [0, "enabled", 0, 0, 0, 0, 0]}

guiderState = {}
guiderState["noneLoaded"] = merge_dicts(guiderOff, noneLoaded, mangaC)
guiderState["cartLoaded"] = merge_dicts(guiderOff, bossLoaded, mangaC)
guiderState["bossLoaded"] = merge_dicts(guiderOff, bossLoaded, mangaC)
guiderState["apogeeLoaded"] = merge_dicts(guiderOff, apogeeLoaded, mangaC)
guiderState["mangaDitherLoaded"] = merge_dicts(guiderOff, mangaDitherLoaded, mangaC)
guiderState["manga10Loaded"] = merge_dicts(guiderOff, manga10Loaded, mangaC)
guiderState["MaStarLoaded"] = merge_dicts(guiderOff, MaStarLoaded, mangaC)
guiderState["mangaStareLoaded"] = merge_dicts(guiderOff, mangaStareLoaded, mangaC)
guiderState["mangaGlobularLoaded"] = merge_dicts(guiderOff, mangaGlobularLoaded, mangaC)
guiderState["apogeemangaDitherLoaded"] = merge_dicts(
    guiderOff, apogeemangaDitherLoaded, mangaC
)
guiderState["apogeemanga10Loaded"] = merge_dicts(guiderOff, apogeemanga10Loaded, mangaC)
guiderState["apogeemangaNoneLoaded"] = merge_dicts(
    guiderOff, apogeemangaLoadedNoSurveyMode, mangaC
)
guiderState["apogeemangaStareLoaded"] = merge_dicts(
    guiderOff, apogeemangaStareLoaded, mangaC
)
guiderState["apogeemangaMaStarLoaded"] = merge_dicts(
    guiderOff, apogeemangaMaStarLoaded, mangaC
)
guiderState["apogeemangaGlobularLoaded"] = merge_dicts(
    guiderOff, apogeemangaGlobularLoaded, mangaC
)
guiderState["apogeeLeadLoaded"] = merge_dicts(guiderOff, apogeeLeadLoaded, mangaC)
guiderState["guiderOn"] = merge_dicts(guiderOn, bossLoaded, mangaC)
guiderState["guiderOnDecenter"] = merge_dicts(guiderOn, mangaDitherLoaded, mangaN)

# platedb state setup
bossPointing = {
    "pointingInfo": [1000, 11, "A", 10.0, 20.0, 1.0, 0.0, 5500, "BOSS", "BOSS"]
}
apogeePointing = {
    "pointingInfo": [2000, 1, "A", 20.0, 30.0, 2.0, 1.0, 10500, "APOGEE-2", "APOGEE"]
}
mangaDitherPointing = {
    "pointingInfo": [3000, 2, "A", 30.0, 40.0, 3.0, 2.0, 5500, "MaNGA", "MaNGA dither"]
}
mangaGlobularPointing = {
    "pointingInfo": [
        3000,
        2,
        "A",
        30.0,
        40.0,
        3.0,
        2.0,
        5500,
        "MaNGA",
        "MaNGA Globular",
    ]
}
manga10Pointing = {
    "pointingInfo": [3001, 2, "A", 30.0, 40.0, 3.0, 2.0, 5500, "MaNGA", "MaNGA 10min"]
}
mangaStarePointing = {
    "pointingInfo": [3001, 2, "A", 30.0, 40.0, 3.0, 2.0, 5500, "MaNGA", "MaNGA Stare"]
}
MaStarPointing = {
    "pointingInfo": [3001, 2, "A", 30.0, 40.0, 3.0, 2.0, 5500, "MaNGA", "MaStar"]
}
apogeeLeadPointing = {
    "pointingInfo": [
        4000,
        3,
        "A",
        40.0,
        50.0,
        4.0,
        3.0,
        10500,
        "APOGEE2&MANGA",
        "APOGEE lead",
    ]
}
apogeeLeadPointingCart7 = {
    "pointingInfo": [
        4000,
        7,
        "A",
        40.0,
        50.0,
        4.0,
        3.0,
        10500,
        "APOGEE2&MANGA",
        "APOGEE lead",
    ]
}
apgoeemangaDitherPointing = {
    "pointingInfo": [
        5000,
        4,
        "A",
        50.0,
        60.0,
        5.0,
        4.0,
        5500,
        "APOGEE-2&MaNGA",
        "MaNGA dither",
    ]
}
apgoeemangaGlobularPointing = {
    "pointingInfo": [
        5000,
        4,
        "A",
        50.0,
        60.0,
        5.0,
        4.0,
        5500,
        "APOGEE-2&MaNGA",
        "MaNGA Globular",
    ]
}
apgoeemanga10Pointing = {
    "pointingInfo": [
        5000,
        4,
        "A",
        50.0,
        60.0,
        5.0,
        4.0,
        5500,
        "APOGEE-2&MaNGA",
        "MaNGA 10min",
    ]
}
apogeemangaStarePointing = {
    "pointingInfo": [
        5001,
        4,
        "A",
        50.0,
        60.0,
        5.0,
        4.0,
        5500,
        "APOGEE-2&MaNGA",
        "MaNGA Stare",
    ]
}
apogeemangaMaStarPointing = {
    "pointingInfo": [
        5001,
        4,
        "A",
        50.0,
        60.0,
        5.0,
        4.0,
        5500,
        "APOGEE-2&MaNGA",
        "MaStar",
    ]
}
apogeeDesignNone = {"apogeeDesign": ["?", -1], "mangaExposureTime": [-1]}
apogeeDesign1000 = {"apogeeDesign": ["longplate", 1000], "mangaExposureTime": [-1]}
apogeeDesignNone_manga_short = {"apogeeDesign": ["?", -1], "mangaExposureTime": [28]}
apogeeDesign1000_manga_short = {
    "apogeeDesign": ["longplate", 1000],
    "mangaExposureTime": [28],
}
noInstrumentPlugged = {"pluggedInstruments": []}
APOGEEInstrumentPlugged = {"pluggedInstruments": ["APOGEE"]}
BOSSInstrumentPlugged = {"pluggedInstruments": ["BOSS"]}
BothInstrumentsPlugged = {"pluggedInstruments": ["BOSS", "APOGEE"]}
platedbState = {}
platedbState["boss"] = merge_dicts(
    bossPointing, apogeeDesignNone, BOSSInstrumentPlugged
)
platedbState["apogee"] = merge_dicts(
    apogeePointing, apogeeDesignNone, APOGEEInstrumentPlugged
)
platedbState["mangaDither"] = merge_dicts(
    mangaDitherPointing, apogeeDesignNone, BOSSInstrumentPlugged
)
platedbState["manga10"] = merge_dicts(
    manga10Pointing, apogeeDesignNone, BOSSInstrumentPlugged
)
platedbState["mangaStare"] = merge_dicts(
    mangaStarePointing, apogeeDesignNone, BOSSInstrumentPlugged
)
platedbState["mangaGlobular"] = merge_dicts(
    mangaGlobularPointing, apogeeDesignNone_manga_short, BOSSInstrumentPlugged
)
platedbState["MaStar"] = merge_dicts(
    MaStarPointing, apogeeDesignNone, BOSSInstrumentPlugged
)
platedbState["MaStar_short"] = merge_dicts(
    MaStarPointing, apogeeDesignNone_manga_short, BOSSInstrumentPlugged
)
platedbState["MaStar_coobs_short"] = merge_dicts(
    MaStarPointing, apogeeDesignNone_manga_short, BothInstrumentsPlugged
)
platedbState["apgoeemangaDither"] = merge_dicts(
    apgoeemangaDitherPointing, apogeeDesignNone, BothInstrumentsPlugged
)
platedbState["apogeemangaGlobular"] = merge_dicts(
    apgoeemangaGlobularPointing, apogeeDesignNone_manga_short, BothInstrumentsPlugged
)
platedbState["apgoeemanga10"] = merge_dicts(
    apgoeemanga10Pointing, apogeeDesignNone, BothInstrumentsPlugged
)
platedbState["apgoeemangaStare"] = merge_dicts(
    apogeemangaStarePointing, apogeeDesignNone, BothInstrumentsPlugged
)
platedbState["apogeemangaMaStar"] = merge_dicts(
    apogeemangaMaStarPointing, apogeeDesignNone, BothInstrumentsPlugged
)
platedbState["apogeeLead"] = merge_dicts(
    apogeeLeadPointing, apogeeDesignNone, BothInstrumentsPlugged
)
platedbState["apogeeLeadCart7"] = merge_dicts(
    apogeeLeadPointingCart7, apogeeDesignNone, BothInstrumentsPlugged
)
platedbState["apogeeLead1000s"] = merge_dicts(
    apogeeLeadPointing, apogeeDesign1000, BothInstrumentsPlugged
)

platedbState["apogeeLead1000sCart7"] = merge_dicts(
    apogeeLeadPointingCart7, apogeeDesign1000, BothInstrumentsPlugged
)
platedbState["apogeeLead_manga_short"] = merge_dicts(
    apogeeLeadPointing, apogeeDesignNone_manga_short, BothInstrumentsPlugged
)
platedbState["apogeeLead1000s_manga_short"] = merge_dicts(
    apogeeLeadPointing, apogeeDesign1000_manga_short, BothInstrumentsPlugged
)
platedbState["coObsNoAPOGEE"] = merge_dicts(BOSSInstrumentPlugged)
platedbState["coObsNoMANGA"] = merge_dicts(APOGEEInstrumentPlugged)
platedbState["coObsNone"] = merge_dicts(noInstrumentPlugged)
platedbState["coObsBoth"] = merge_dicts(BothInstrumentsPlugged)

# gcamera state setup
gcameraTempOk = {"cooler": [-40, -40, -40, 80, 1, "Correcting"]}
gcameraSeqNo = {"nextSeqno": [1234], "filename": ["/data/gcam/54321/gimg-1234.fits.gz"]}
gcameraSimulatingOff = {"simulating": ["Off", "", 0]}
gcameraState = {}
gcameraState["ok"] = merge_dicts(gcameraTempOk, gcameraSeqNo, gcameraSimulatingOff)

# ecamera state setup: just like the gcamera, but different name.
ecameraState = {}
ecameraState["ok"] = merge_dicts(gcameraTempOk, gcameraSeqNo, gcameraSimulatingOff)

# sop state setup
bypasses = [
    "ffs",
    "lamp_ff",
    "lamp_hgcd",
    "lamp_ne",
    "axes",
    "isBoss",
    "isApogee",
    "isMangaDither",
    "isMangaStare",
    "isManga10",
    "isMangaGlobular",
    "isApogeeManga10",
    "isApogeeLead",
    "isApogeeMangaDither",
    "isApogeeMangaStare",
    "isApogeeMangaGlobular",
    "gangToCart",
    "gangToPodium",
    "slewToField",
    "guiderDark",
    "guider_decenter",
    "isMaStar",
    "isApogeeMangaMaStar",
]
sopNoBypass = {"bypassNames": bypasses, "bypassedNames": []}
sopEmptyCommands = {
    "surveyCommands": (
        "gotoField",
        "gotoStow",
        "gotoInstrumentChange",
        "gotoAll60",
        "gotoStow60",
    ),
    "survey": ["UNKNOWN", "None"],
}
sopBossCommands = {
    "surveyCommands": (
        "gotoField",
        "gotoStow",
        "gotoInstrumentChange",
        "gotoAll60",
        "gotoStow60",
        "doBossCalibs",
        "doBossScience",
    ),
    "survey": ["BOSS", "None"],
}
sopMangaCommands = {
    "surveyCommands": (
        "gotoField",
        "gotoStow",
        "gotoInstrumentChange",
        "gotoAll60",
        "gotoStow60",
        "doBossCalibs",
        "doMangaDither",
        "doMangaSequence",
    ),
    "survey": ["MaNGA", "MaNGA dither"],
}
sopApogeeCommands = {
    "surveyCommands": (
        "gotoField",
        "gotoStow",
        "gotoInstrumentChange",
        "gotoAll60",
        "gotoStow60",
        "doApogeeScience",
        "doApogeeSkyFlats",
        "gotoGangChange",
        "doApogeeDomeFlat",
    ),
    "survey": ["APOGEE", "None"],
}
sopApogeeMangaCommands = {
    "surveyCommands": (
        "gotoField",
        "gotoStow",
        "gotoInstrumentChange",
        "gotoAll60",
        "gotoStow60",
        "doBossCalibs",
        "doApogeeMangaDither",
        "doApogeeMangaSequence",
        "doApogeeSkyFlats",
        "gotoGangChange",
        "doApogeeDomeFlat",
    ),
    "survey": ["APOGEE-2&MaNGA", "APOGEE lead"],
}
sopState = {}
sopState["ok"] = merge_dicts(sopNoBypass, sopEmptyCommands)

# apo state setup
weather = {
    "pressure": [2],
    "windd": [2],
    "winds": [2],
    "gustd": [2],
    "gusts": [2],
    "airTempPT": [2],
    "dpTempPT": [2],
    "truss25m": [2],
    "humidity": [2],
    "dusta": [2],
    "dustb": [2],
    "windd25m": [2],
    "winds25m": [2],
}
apoState = {}
apoState["default"] = merge_dicts(weather)

hartmannState = {}
hartmannState["default"] = {"sp1Residuals": [0, 0, "OK"], "sp2Residuals": [0, 0, "OK"]}
hartmannState["blue_fails"] = {
    "sp1Residuals": [0, 0, "Move blue ring 2 degrees."],
    "sp2Residuals": [0, 0, "OK"],
}


class Cmd(object):
    """
    Fake commander object, keeps the message level and message for
    all messages sent through it.
    """

    def __init__(self, verbose=False):
        """Save the level of any messages that pass through."""
        self.verbose = verbose
        self.finished = False
        self.nFinished = 0
        self.didFail = False
        self.command = None  # this is the command text
        self.cParser = parser.CommandParser()
        self.clear_msgs()
        self.cmdr = None  # to make an Actor happy
        self.mid = 0  # to make an Actor happy

        # Always fail when failOn is called as a command.
        self.failOn = None
        # Increase failOnCount to fail on the Nth call of failOn.
        self.failOnCount = 1

        # to keep track of whether BOSS hasn't been readout.
        self.bossNeedsReadout = False

        # To run fxn on command
        self.runOn = None
        self.runOnCount = 1

    def __repr__(self):
        return "TestHelperCmdr-%s" % ("finished" if self.finished else "alive")

    def _msg(self, txt, level):
        if self.verbose:
            # because "print" isn't threadsafe in py27
            sys.stderr.write("%s %s\n" % (level, txt))
            sys.stderr.flush()
        self.levels += level
        self.messages.append(txt)

    def _checkFinished(self):
        if self.finished:
            badTxt = "!!!!!This cmd already finished %d times!" % self.nFinished
            self._msg(badTxt, "w")
        self.nFinished += 1

    def clear_msgs(self):
        """Clear all message text, levels, and calls."""
        self.levels = ""
        self.messages = []
        self.calls = []
        self.replyList = []

    def reset(self):
        """Clear messages, reset finished state, etc."""
        self.clear_msgs()
        self.finished = False
        self.nFinished = 0
        self.didFail = False
        self.bossNeedsReadout = False

    def inform(self, txt):
        self._msg(txt, "i")
        # fake-set the model, if needs-be
        self.use_keywords(txt)

    def respond(self, txt):
        self._msg(txt, "i")

    def diag(self, txt):
        self._msg(txt, "d")

    def warn(self, txt):
        self._msg(txt, "w")

    def error(self, txt):
        self._msg(txt, "e")

    def fail(self, txt):
        self._checkFinished()
        self._msg(txt, "f")
        self.finished = True
        self.didFail = True

    def finish(self, txt=""):
        self._checkFinished()
        self._msg(txt, "F")
        self.finished = True

    def isAlive(self):
        return not self.finished

    def use_keywords(self, txt):
        """
        Update a model keyword, given an inform-level output.
        NOTE: TBD: This is a stupid way of faking the parser, but I'll live with it for now.
        """
        keys = ("surveyCommands", "survey")
        for key in keys:
            gotKey = txt.split("=")[0]
            if key == gotKey:
                val = txt.split("=")[-1].split(",")
                val = [x.strip().strip('"') for x in val]
                globalModels["sop"].keyVarDict[key].set(val)

    def call(self, *args, **kwargs):
        """
        Pretend to complete command successfully, or not, in a thread-safe manner.

        NOTE: had to make this threadsafe, as cmd calls were overwriting
        each other's cmdStr below, causing testcase weirdness.
        Could this be a source of problems in the actual Cmdr?
        """
        with call_lock:
            return self._call(*args, **kwargs)

    def check_fail(self, command):
        """Return True if we should fail this command."""
        if self.failOn is not None and command == self.failOn:
            if self.failOnCount == 1:
                self.didFail = True
                return True
            else:
                self.failOnCount -= 1
        return False

    def _call(self, *args, **kwargs):
        """Pretend to complete command successfully, or not. (not thread safe)"""

        def _finish(didFail, args):
            cmdVar = keyvar.CmdVar(args)
            cmdVar.replyList = self.replyList
            # we were supposed to monitor a keyword, so put something on the stack in response.
            try:
                for kv in args.get("keyVars", []):
                    cmdVar.keyVarDataDict[kv] = []
                    cmdVar.keyVarDataDict[kv].append(kv.valueList)
            except AttributeError:
                pass  # this is a fake thread call, so just ignore keyVars trouble.
            # see opscore.actor.keyvar.DoneCodes/FailCodes.
            cmdVar.lastCode = "F" if didFail else ":"
            self.didFail = didFail
            return cmdVar

        didFail = False

        # for handling FakeThread stuff.
        if args:
            text = str(*args).strip()
            self._msg(text, "c")
            didFail = self.check_fail(text)
            self.calls.append(text)
            return _finish(didFail, args)

        # for handling "real" commands
        cmdStr = kwargs.get("cmdStr")
        timeLim = kwargs.get("timeLim", -1)
        actor = kwargs.get("actor", None)
        caller = kwargs.get("forUserCmd", None)
        baseText = " ".join((str(actor), cmdStr, "<<timeLim=%s>>" % (timeLim)))
        if caller is not None and not isinstance(caller, Cmd):
            raise TypeError(
                "You can't call %s with forUserCmd=%s." % (baseText, caller)
            )
        try:
            cmd = self.cParser.parse(cmdStr)
            cmdTxt = " ".join((actor, cmd.string))
            other = "<<timeLim=%.1f>>" % (timeLim)
            text = " ".join((cmdTxt, other))
        except (parser.ParseError, AttributeError):
            text = baseText
        self._msg(text, "c")
        command = text.split("<<")[0].strip()
        self.command = command
        self.calls.append(command)

        # run on
        if self.runOn:
            self.inject_command(command)

        if self.check_fail(command):
            didFail = True
            # handle commands where we have to do something with a failure.
            fail_func = getattr(self, actor + "_fail", None)
            if fail_func is not None:
                fail_func(**kwargs)
        else:
            # Handle commands where we have to set a new state or do something more complex.
            succeed_func = getattr(self, actor + "_succeed", None)
            if succeed_func is not None:
                didFail = succeed_func(**kwargs)

        return _finish(didFail, kwargs)

    def inject_command(self, command):
        """Try to inject a function into at a given command"""
        cmd, fxn = self.runOn
        if cmd == command:
            if self.runOnCount == 1:
                # run the function and set the counter to 0
                fxn()
                self.runOnCount = 0
            elif self.runOnCount != 0:
                self.runOnCount -= 1

    def apogee_succeed(self, **kwargs):
        """Handle apogee commands as successes, and update appropriate keywords."""

        didFail = False
        cmdStr = kwargs.get("cmdStr")
        try:
            cmd = self.cParser.parse(cmdStr)
            stop = ("stop" in cmd.keywords[0].name) or ("abort" in cmd.keywords[0].name)
            if cmd.name == "dither":
                key, newVal = self._get_dither(cmd.keywords)
            elif cmd.name == "shutter":
                key, newVal = self._get_shutter(cmd.keywords)
            elif cmd.name == "expose" and not stop:
                key, newVal = self._get_expose(cmd.keywords)
            elif cmd.name == "expose" and stop:
                # Don't worry about state, just succeed at stopping.
                return didFail
            else:
                raise ValueError("I don't know what to do with this: %s" % cmdStr)
        except ValueError as e:
            print("ValueError in apogee_succeed:", e)
            didFail = True
        else:
            globalModels["apogee"].keyVarDict[key].set(newVal[key])

        return didFail

    def _get_dither(self, keywords):
        """Return the key/value pair for a requested new dither position."""
        cmdVal = keywords["namedpos"].values[0]
        key = "ditherPosition"
        if cmdVal == "A":
            newVal = ditherA
        elif cmdVal == "B":
            newVal = ditherB
        else:
            raise ValueError("Unknown dither position: %s" % cmdVal)
        return key, newVal

    def _get_shutter(self, keywords):
        """Return the key/value pair for a requested new shutter position."""
        key = "shutterLimitSwitch"
        if "open" in keywords:
            newVal = shutterOpen
        elif "close" in keywords:
            newVal = shutterClosed
        else:
            raise ValueError("Unknown shutter position: %s" % keywords)
        return key, newVal

    def _get_expose(self, keywords):
        """Return the key/value pair for a requested exposure."""
        key = "utrReadState"
        time = keywords["time"].values[0]
        nReads = float(time) / 10.0
        name = keywords["object"].values[0]
        newVal = {key: (name, "Reading", 1, nReads)}
        return key, newVal

    def _fake_boss_readout(self, cmd):
        """Behave like the real camera regarding when readouts are allowed or not."""

        currentExpId = globalModels["boss"].keyVarDict["exposureId"].getValue()

        didFail = False
        readout = "readout" in cmd.keywords
        noreadout = "noreadout" in cmd.keywords
        stop = ("stop" in cmd.keywords[0].name) or ("abort" in cmd.keywords[0].name)
        # NOTE: try to be explicit about the fail/success status here.
        if (readout or stop) and self.bossNeedsReadout:
            self.bossNeedsReadout = False
            time.sleep(1)  # waiting a short bit helps with lamp timings.
            globalModels["boss"].keyVarDict["exposureId"].set(
                [
                    currentExpId + 1,
                ]
            )
        elif (readout or stop) and not self.bossNeedsReadout:
            didFail = True
            self.error("Error!!! boss says: No exposure to act on.")
        elif not readout and self.bossNeedsReadout:
            didFail = True
            self.error(
                "Error!!! Cannot take BOSS exposure: need to readout previous one!"
            )
        elif noreadout:
            self.bossNeedsReadout = True
            time.sleep(1)  # waiting a short bit helps with lamp timings.
        else:
            self.bossNeedsReadout = False
            time.sleep(1)  # waiting a short bit helps with lamp timings.
            globalModels["boss"].keyVarDict["exposureId"].set(
                [
                    currentExpId + 1,
                ]
            )
        return didFail

    def boss_succeed(self, **kwargs):
        """Handle boss commands as successes, and remember if we need to readout."""

        didFail = False

        cmdStr = kwargs.get("cmdStr")
        cmd = self.cParser.parse(cmdStr)
        if cmd.name == "exposure":
            didFail = self._fake_boss_readout(cmd)
        else:
            # any other boss commands just succeed.
            didFail = False

        return didFail

    def boss_fail(self, **kwargs):
        """Handle boss commands as failures, deal with readouts,
        and update appropriate keywords."""

        cmdStr = kwargs.get("cmdStr")
        cmd = self.cParser.parse(cmdStr)
        if cmd.name == "exposure":
            self._fake_boss_readout(cmd)
        if cmd.name == "moveColl":
            self.replyList.append(messages.Reply("", [messages.Keyword("Timeout")]))

    def tcc_succeed(self, **kwargs):
        """Handle tcc commands as successes, and update appropriate keywords."""
        didFail = False
        try:
            cmdStr = kwargs.get("cmdStr")
            if "track" in cmdStr:
                result = "axisCmdState", axisCmdState_tracking
            else:
                result = None
        except ValueError as e:
            print("ValueError in tcc_succeed:", e)
            didFail = True
        else:
            if result is None:
                # key was already newVal, so do nothing.
                return didFail
            else:
                key, newVal = result
            globalModels["tcc"].keyVarDict[key].set(newVal[key])

        return didFail

    def mcp_succeed(self, **kwargs):
        """Handle mcp commands as successes, and update appropriate keywords."""

        didFail = False

        try:
            cmdStr = kwargs.get("cmdStr")
            if "ff." in cmdStr:
                result = self._do_lamp("ff", cmdStr.split(".")[-1])
            elif "ne." in cmdStr:
                result = self._do_lamp("ne", cmdStr.split(".")[-1])
            elif "hgcd." in cmdStr:
                result = self._do_lamp("hgCd", cmdStr.split(".")[-1])
            elif "wht." in cmdStr:
                # these two lamps are always off. So do nothing.
                return
            elif "uv." in cmdStr:
                return
            elif "ffs." in cmdStr:
                result = self._do_ffs(cmdStr.split(".")[-1])
            elif "sem." in cmdStr:
                result = list(semaphoreGood.items())[0]
            else:
                raise ValueError("Unknown mcp command: %s" % cmdStr)
        except ValueError as e:
            print("ValueError in mcp_succeed:", e)
            didFail = True
        else:
            if result is None:
                # key was already newVal, so do nothing.
                return didFail
            else:
                key, newVal = result
            globalModels["mcp"].keyVarDict[key].set(newVal)

        return didFail

    def _do_lamp(self, lamp, state):
        """
        Change lamp to new state.

        Return the new key/value pair, or None if nothing is to be changed.
        """
        key = lamp + "Lamp"
        val = globalModels["mcp"].keyVarDict[key].getValue()

        if (state == "on" and sum(val) == 4) or (state == "off" and val == 0):
            return None
        if state == "on":
            newVal = [1] * 4
        elif state == "off":
            newVal = [0] * 4
        else:
            raise ValueError("Unknown %sLamp state: %s" % (lamp, state))
        return key, newVal

    def _do_ffs(self, state):
        """Change ffs screens to new state"""
        key = "ffsStatus"
        if state == "close":
            newVal = ffsClosed["ffsStatus"]
        elif state == "open":
            newVal = ffsOpen["ffsStatus"]
        else:
            raise ValueError("Unknown ffs state: %s" % state)
        return key, newVal

    def guider_succeed(self, **kwargs):
        """Handle guider commands as successes, and update appropriate keywords."""

        didFail = False
        cmdStr = kwargs.get("cmdStr")
        try:
            cmd = self.cParser.parse(cmdStr)
            if cmd.name == "mangaDither":
                key, newVal = self._get_mangaDither(cmd.keywords)
            elif cmd.name == "decenter":
                key, newVal = self._get_decenter(cmd.keywords)
            elif cmd.name == "on":
                # This keeps guiderThread happy:
                self.replyList.append(messages.Reply("", [messages.Keyword("Timeout")]))
                key, newVal = "guideState", guiderOn
                # guider on *should* fail, because it times out, since the command
                # won't complete until the guider is turned off.
                didFail = True
            elif cmd.name == "off":
                key, newVal = "guideState", guiderOff
            elif cmd.name == "flat":
                time.sleep(1)  # waiting a short bit helps with lamp timings.
                return didFail
            elif cmd.name in ("axes", "scale", "focus"):
                # just succeed on axes clear.
                return False
            elif cmd.name == "setRefractionBalance":
                # just succeed
                return False
            elif cmd.name == "loadCartridge":
                globalModels["guider"].keyVarDict["cartridgeLoaded"].set(
                    bossLoaded["cartridgeLoaded"]
                )
                globalModels["guider"].keyVarDict["survey"].set(bossLoaded["survey"])
                return False
            elif cmd.name == "makeMovie":
                # just succeed
                return True
            else:
                raise ValueError("I don't know what to do with this: %s" % cmdStr)
        except ValueError as e:
            print("ValueError in guider_succeed:", e)
            didFail = True
        else:
            globalModels["guider"].keyVarDict[key].set(newVal[key])

        return didFail

    def _get_mangaDither(self, keywords):
        """Set a new mangaDither position."""
        key = "decenter"
        pos = keywords["ditherPos"].values[0]
        if pos == "N":
            newVal = mangaN
        elif pos == "S":
            newVal = mangaS
        elif pos == "E":
            newVal = mangaE
        elif pos == "C":
            newVal = mangaCenabled
        else:
            raise ValueError(
                "I don't know what to do with this mangaDither: %s" % keywords
            )
        globalModels["guider"].keyVarDict["mangaDither"].set(newVal["mangaDither"])
        return key, newVal

    def _get_decenter(self, keywords):
        """Change decenter to new state"""
        key = "decenter"
        if "on" in keywords:
            newVal = yesDecenter
        elif "off" in keywords:
            newVal = noDecenter
        else:
            raise ValueError("Unknown decenter state: %s" % (keywords))
        return key, newVal

    def guider_fail(self, **kwargs):
        """Handle guider commands as failures, and update appropriate keywords."""
        cmdStr = kwargs.get("cmdStr")
        key = None
        cmd = self.cParser.parse(cmdStr)
        if cmd.name == "on":
            key, newVal = "guideState", guiderFailed
        if cmd.name == "mangaDither":
            # These usually timeout, so set a message thusly.
            self.replyList.append(messages.Reply("", [messages.Keyword("Timeout")]))

        if key is not None:
            globalModels["guider"].keyVarDict[key].set(newVal[key])


# Fake logging.
# logBuffer and iologbuffer is where the log strings will end up.
class FakeFileStringIO(io.StringIO):
    """A StringIO that remembers a basedir."""

    def __init__(self, basedir=None):
        self.basedir = basedir
        io.StringIO.__init__(self)


# NOTE: need this to be global, so I can grab it inside a test and check, e.g.
# self.assertIn('toy starting up.',TestHelper.logBuffer.getvalue())
global logBuffer
global iologBuffer
logBuffer = None
iologBuffer = None


def setupRootLogger(basedir, level=logging.INFO, hackRollover=False):
    """
    Save all log output into a string for later searching.

    When testing an Actor subclass, replace Actor.setupRootLogger as part of
    your Test.setUpClass():
        from actorcore import Actor
        ....
            Actor.setupRootLogger = TestHelper.setupRootLogger
    """

    # NOTE: need this to be global, so I can grab it inside a test.
    global logBuffer
    logBuffer = FakeFileStringIO(basedir=basedir)

    rootHandler = logging.StreamHandler(logBuffer)
    rootHandler.setLevel(logging.DEBUG)

    rootLogger = logging.getLogger()
    rootLogger.setLevel(level)
    rootLogger.addHandler(rootHandler)

    # disable stderr output
    for h in rootLogger.handlers:
        if isinstance(h, logging.StreamHandler) and h.stream == sys.stderr:
            h.setLevel(logging.CRITICAL + 1)
            rootLogger.removeHandler(h)

    return rootLogger


def fakeOpsFileLogger(dirname, name, level=logging.INFO, **kwargs):
    """
    Make a fake ops file logger that logs to a string.

    When testing an ICC subclass, replace ICC.makeOpsFileLogger as part of
    your Test.setUpClass():
        from actorcore import ICC
        ....
            ICC.makeOpsFileLogger = TestHelper.fakeOpsFileLogger
    """

    # NOTE: need this to be global, so I can grab it inside a test.
    global iologBuffer
    iologBuffer = FakeFileStringIO(basedir=dirname)

    handler = logging.StreamHandler(iologBuffer)
    handler.setLevel(logging.DEBUG)

    logger = logging.getLogger()
    logger.setLevel(level)
    logger.addHandler(handler)

    return logger


class ActorTester(object):
    """
    Helper class for actor-related tests. Sets up a reasonable initial model state.

    Expects that self.name be set to the name of this actor before setUp().
    test suites should subclass this and unittest, in that order.
    """

    def setUp(self):
        """Set some defaults and initialize self.actorState."""
        self.timeout = 5
        # Set this to True to fail if there is no cmd_calls defined for that test.
        self.fail_on_no_cmd_calls = False
        # If we've read in a list of cmd_calls for this class, prep them for use!
        if hasattr(self, "class_calls"):
            test_name = self.id().split(".")[-1]
            self.test_calls = self.class_calls.get(test_name, None)
        else:
            self.test_calls = []

        try:
            if self.verbose:
                print("\n")  # newline after unittest's docstring printing.
        except NameError:
            self.verbose = False

        # appends custom assert messages to the default text (very useful!)
        self.longMessage = True

        self.cmd = Cmd(verbose=self.verbose)

        # default status for some actors
        models = {
            "mcp": mcpState["all_off"],
            "apogee": apogeeState["A_closed"],
            "tcc": tccState["halted"],
            "boss": bossState["idle"],
            "apo": apoState["default"],
            "hartmann": hartmannState["default"],
        }

        if getattr(self, "actor", None) is None:
            if self.name in ("boss", "gcamera"):
                productName = self.name + "ICC"
            elif self.name not in ("mcp", "tcc"):
                productName = self.name + "Actor"
            else:
                productName = self.name
            self.actor = FakeActor.newActor(
                self.name,
                productName=productName,
                cmd=self.cmd,
                attachCmdSets=self.attachCmdSets,
            )

        self.actorState = ActorState(
            cmd=self.cmd, models=list(models.keys()), modelParams=list(models.values())
        )
        self.actorState.actor = self.actor

    def _run_cmd(self, cmdStr, queue, empty=False):
        """
        Run the command in cmdStr on the current actor, and return its msg.
        If empty is set, don't fail on an empty queue.
        """
        self.cmd.rawCmd = cmdStr
        self.actor.runActorCmd(self.cmd)
        if queue is not None:
            return self._queue_get(queue, empty)
        else:
            return None

    def _queue_get(self, queue, empty=False):
        """
        Get a message off the queue, and fail with a message if there isn't one.
        If empty is set, don't fail on an empty queue.
        """
        try:
            return queue.get(timeout=1)  # short timeout, so we don't have to wait.
        except queue.Empty:
            if not empty:
                self.fail("No message on the reply queue!")
            return None

    def _check_cmd(self, nCall, nInfo, nWarn, nErr, finish, didFail=False, **kwargs):
        """Check cmd levels, whether it finished, and the cmd.call stack."""
        if self.test_calls is not None:
            self._check_calls(self.test_calls, self.cmd.calls)
        else:
            errMsg = "%s doesn't have a cmd_calls definition!" % self.id()
            print(("WARNING: %s" % errMsg))
            self.assertFalse(self.fail_on_no_cmd_calls, errMsg)

        self._check_levels(nCall, nInfo, nWarn, nErr)
        self.assertEqual(self.cmd.finished, finish)

        if didFail and finish:
            self.assertEqual(self.cmd.didFail, didFail)
            # if we really "fail"ed, there should be exactly one fail message.
            self.assertEqual(self.cmd.levels.count("f"), 1)
        elif not didFail and finish:
            # if we "finish"ed, there should be exactly one finish message, and no fails.
            self.assertEqual(self.cmd.levels.count("F"), 1)
            self.assertEqual(self.cmd.levels.count("f"), 0)
        else:
            # if we didn't "fail", there should be exactly 0 fail messages.
            self.assertEqual(self.cmd.levels.count("f"), 0)

    def _check_levels(self, nCall, nInfo, nWarn, nErr):
        """Check that the cmd levels match the expected result."""
        ll = self.cmd.levels
        counts = (ll.count("c"), ll.count("i"), ll.count("w"), ll.count("e"))
        self.assertEqual(counts, (nCall, nInfo, nWarn, nErr))

    def _check_calls(self, test_calls, calls):
        """
        Check that the actual cmd calls match the expected result.
        Have to compare one "block" at a time, because of threading.
        """
        n = 0
        actual, expected = [], []
        for sublist in test_calls:
            i = len(sublist)
            actual.extend(sorted(calls[n : n + i]))
            expected.extend(sorted(sublist))
            n = n + i
        # tack on anything else that we missed.
        actual.extend(calls[n:])
        self.assertEqual(actual, expected)

    def _load_cmd_calls(self, class_name):
        """Load the cmd calls for this test class from cmd_calls/."""
        cmdFile = os.path.join("cmd_calls", class_name + ".txt")
        self.class_calls = {}
        name = ""
        # Don't like using re, but ConfigParser barfs on these sorts of files.
        # Define a group on the stuff inside the brackets.
        header = re.compile(r"\[(.*)\]")
        with open(cmdFile) as f:
            data = f.readlines()
        for line in data:
            line = line.strip()
            if line == "":
                # Blank lines either separate blocks, or new headers.
                # assume a new block follows, and clean up later if necessary.
                self.class_calls[name].append([])
                continue
            if line[0] == "#":
                # Ignore comments.
                continue
            re_match = header.match(line)
            if re_match:
                # remove empty lists due to blank line separating test function headers
                if name and self.class_calls[name] == []:
                    self.class_calls[name].remove(-1)
                name = re_match.groups(0)[0]
                # NOTE: If this happens, then we've duplicated a cmd list.
                assert name not in self.class_calls, (
                    "%s missing from cmd_calls: check for duplicates?" % name
                )
                self.class_calls[name] = [[]]
            else:
                self.class_calls[name][-1].append(line)


#
# Stuff to fake actors/models/etc.
#


class Model(object):
    """quick replacement for Model in opscore/actorcore."""

    def __init__(self, actor, keyDict={}):
        self.actor = actor
        self.myKeys = keys.KeysDictionary.load(actor)

        self.keyVarDict = {}
        for k, v in list(keyDict.items()):
            self.keyVarDict[k] = keyvar.KeyVar(actor, self.myKeys[k])  # ,doPrint=True)
            self.keyVarDict[k].set(v)

    def setKey(self, key, value):
        """Set keyVarDict[key] = value, with appropriate type conversion."""
        self.keyVarDict[key].set(value)

    def get_TypedValue(self, name):
        """Returns the TypedValue of the actorkey actor[name]."""
        return self.myKeys[name].typedValues.vtypes[0]


# ...


class FakeActor(Actor.SDSSActor):
    """An actor that doesn't do anything important during init()."""

    @staticmethod
    def newActor(name, location="APO", *args, **kwargs):
        """Default to APO, but allow setting the location. Just init a fakeActor."""
        return FakeActor(name, location=location, **kwargs)

    def __init__(
        self,
        name,
        productName=None,
        cmd=None,
        configFile=None,
        location=None,
        attachCmdSets=True,
    ):

        self.name = name
        self.location = location or "LOCAL"
        self.productName = productName if productName else self.name

        mod = importlib.import_module(self.productName)
        class_path = os.path.dirname(mod.__file__)
        self.product_dir = class_path

        self.configFile = configFile or os.path.join(
            self.product_dir, f"etc/{self.name}.yaml"
        )

        self.cmdLog = logging.getLogger("cmds")
        self.logger = logging.getLogger("logger")
        if cmd is not None:
            self.bcast = cmd
            self.cmdr = cmd

        # try to load the config file(s), don't worry if it fails.
        try:
            self.read_config_files()
        except BaseException:
            print("Warning: failed to parse config file(s).")
            pass

        # Disable logging to reduce clutter, since these are just
        # here to keep attachAllCmdSets, etc. happy.
        logging.disable(logging.CRITICAL)

        self.version = "trunk"

        self.commandSets = {}
        self.handler = validation.CommandHandler()
        if attachCmdSets:
            self.attachAllCmdSets()

    def sendVersionKey(self, cmd):
        cmd.inform("version=FAKE!")

    def callCommand(self, cmdStr):
        """Send ourselves a command, via a new cmd."""
        self.newCmd = Cmd()
        self.newCmd.call(actor=self.name, cmdStr=cmdStr)


class ActorState(object):
    """
    A fake version of ActorState, as used in guiderActor and sopActor.
    Holds models and other actors, to facilitate fake global communication.
    """

    dispatcherSet = False

    def __init__(self, cmd=None, actor=None, models=[], modelParams=[]):
        """
        Pass a list of models to create, and modelParams as a list
        of dicts to associate with each model a fake keyVarDict.
        """
        if cmd is None:
            cmd = Cmd()
        self.models = {}
        if self.dispatcherSet:
            Model.setDispatcher(cmd)
            self.dispatcherSet = True
        for m, p in zip(models, modelParams):
            self.models[m] = Model(m, p)
        global globalModels
        globalModels = self.models
