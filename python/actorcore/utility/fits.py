import gzip
import logging
import os
import tempfile
import threading

import astropy.io.fits as fits
import numpy

from opscore.utility.qstr import qstr


def extendHeader(cmd, header, cards):
    """Add all the cards to the header."""

    for name, val, comment in cards:
        try:
            header.update(name, val, comment)
        except BaseException:
            cmd.warn('text="failed to add card: %s=%s (%s)"' % (name, val, comment))


def makeCard(cmd, name, value, comment=""):
    """Creates a fits Card. Does not raise exceptions."""

    try:
        return fits.Card(name, value, comment)
    except BaseException:
        errStr = "failed to make %s card from %s" % (name, value)
        cmd.warn("text=%s" % (qstr(errStr)))
        return ("comment", errStr, "")


def makeCardFromKey(
    cmd, keyDict, keyName, cardName, cnv=None, idx=None, comment="", onFail=None
):
    """
    Creates a fits Card from a Key. Does not raise exceptions.
    If comment is None, use "keyName: keyDict[keyName].help" for the comment string.
    """

    try:
        val = keyDict[keyName]
    except KeyError:
        errStr = "failed to fetch %s" % (keyName)
        cmd.warn("text=%s" % (qstr(errStr)))
        return makeCard(cmd, cardName, onFail, errStr)

    try:
        if idx is not None:
            val = val[idx]
        else:
            val = val.getValue()
    except Exception as e:
        errStr = "failed to index %s by %s from %s for %s: %s" % (
            val,
            idx,
            keyName,
            cardName,
            e,
        )
        cmd.warn("text=%s" % (qstr(errStr)))
        return makeCard(cmd, cardName, onFail, errStr)

    if comment is None:
        # try to use the help string from the keyVar.
        try:
            txt = val.help
            # For single-value keys, the help is often at the Key level.
            if txt is None:
                txt = keyDict[keyName].key.help
            comment = "%s: %s" % (keyName, txt)
        except BaseException:
            comment = ""

    if cnv is not None:
        try:
            val = cnv(val)
        except Exception as e:
            errStr = "failed to convert %s from %s for %s using %s: %s" % (
                val,
                keyName,
                cardName,
                cnv,
                e,
            )
            cmd.warn("text=%s" % (qstr(errStr)))
            return makeCard(cmd, cardName, onFail, errStr)

    return makeCard(cmd, cardName, val, comment)


def mcpCards(models, cmd=None):
    """Return a list of fits Cards describing the MCP state."""

    d = []

    mcpDict = models["mcp"].keyVarDict
    for lampKey in ("ffLamp", "neLamp", "hgCdLamp"):
        cardName = lampKey[:-4].upper()
        card = makeCardFromKey(
            cmd,
            mcpDict,
            lampKey,
            cardName,
            cnv=_cnvListCard,
            comment="%s lamps 1:on 0:0ff" % (cardName),
            onFail="X X X X",
        )
        d.append(card)

    def _cnvFFSCard(petals):
        """Convert the mcp.ffsStatus keyword to what we want."""

        ffDict = {"01": "1", "10": "0"}
        return " ".join([str(ffDict.get(p, "X")) for p in petals])

    card = makeCardFromKey(
        cmd,
        mcpDict,
        "ffsStatus",
        "FFS",
        cnv=_cnvFFSCard,
        comment="Flatfield Screen 1:closed 0:open",
        onFail="X X X X X X X X",
    )
    d.append(card)

    return d


def apoCards(models, cmd=None):
    """Return a list of fits Cards describing APO weather state."""

    cards = []
    weatherDict = models["apo"].keyVarDict

    cards.append(
        makeCardFromKey(
            cmd,
            models["apo"].keyVarDict,
            "version",
            "v_apo",
            comment="version of the current apoActor",
            onFail="Unknown",
        )
    )

    keys = (
        ("pressure", None, float),
        ("windd", None, float),
        ("winds", None, float),
        ("gustd", None, float),
        ("gusts", None, float),
        ("airTempPT", "airtemp", float),
        ("dpTempPT", "dewpoint", float),
        ("truss25m", "trustemp", float),
        # ('dpErrPT', None, str),
        ("humidity", None, float),
        ("dusta", None, float),
        ("dustb", None, float),
        ("windd25m", None, float),
        ("winds25m", None, float),
    )

    for keyName, cardName, cnv in keys:
        if not cardName:
            cardName = keyName
        cardName = cardName.upper()
        card = makeCardFromKey(
            cmd, weatherDict, keyName, cardName, comment=None, cnv=cnv, onFail="NaN"
        )
        cards.append(card)

    return cards


def lcoTCCCards(models, cmd=None):
    """Return a list of fits Cards describing the TCC state."""

    cards = []

    tccDict = models["tcc"].keyVarDict

    try:
        objSys = tccDict["objSys"]
        objSysName = str(objSys[0])
    except Exception:
        objSysName = "unknown"
        if cmd:
            cmd.warn(
                'text="could not get objsys and epoch from tcc.objSys=%s"' % (objSys)
            )
    cards.append(makeCard(cmd, "OBJSYS", objSysName, "The TCC objSys"))

    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "objNetPos",
            "RADEG",
            cnv=_cnvPVTPosCard,
            idx=0,
            comment="RA of telescope pointing(deg)",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "objNetPos",
            "DECDEG",
            cnv=_cnvPVTPosCard,
            idx=1,
            comment="Dec of telescope pointing (deg)",
            onFail="NaN",
        )
    )

    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "axePos",
            "RA",
            cnv=float,
            idx=0,
            comment="RA axis pos. (approx, deg)",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "axePos",
            "DEC",
            cnv=float,
            idx=1,
            comment="DEC axis pos. (approx, deg)",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "tccHA",
            "HA",
            cnv=float,
            idx=0,
            comment="HA axis pos. (approx, deg)",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "axePos",
            "IPA",
            cnv=float,
            idx=2,
            comment="Rotator axis pos. (approx, deg)",
            onFail="NaN",
        )
    )

    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "secFocus",
            "FOCUS",
            idx=0,
            cnv=float,
            comment="User-specified focus offset (um)",
            onFail="NaN",
        )
    )

    # temps
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "tccTemps",
            "T_OUT",
            idx=0,
            cnv=float,
            comment="Outside temperature deg C.",
            onFail="NaN",
        )
    )

    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "tccTemps",
            "T_IN",
            idx=1,
            cnv=float,
            comment="Inside temperature deg C.",
            onFail="NaN",
        )
    )

    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "tccTemps",
            "T_PRIM",
            idx=2,
            cnv=float,
            comment="Primary mirror temperature deg C.",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "tccTemps",
            "T_CELL",
            idx=3,
            cnv=float,
            comment="Cell temperature deg C.",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "tccTemps",
            "T_FLOOR",
            idx=4,
            cnv=float,
            comment="Floor temperature deg C.",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "secTrussTemp",
            "T_TRUSS",
            idx=0,
            cnv=float,
            comment="Truss temperature deg C. Used for automatic focus correction",
            onFail="NaN",
        )
    )

    try:
        secOrient = tccDict["secOrient"]
        orientNames = ("piston", "xtilt", "ytilt", "xtran", "ytran", "zrot")
        for i in range(len(orientNames)):
            cards.append(
                makeCard(
                    cmd, "M2" + orientNames[i], float(secOrient[i]), "TCC SecOrient"
                )
            )
    except Exception as e:
        cmd.warn("text='failed to generate the SecOrient cards: %s'" % (e))

    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "scaleFac",
            "SCALE",
            idx=0,
            cnv=float,
            comment="User-specified scale factor",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "mitutoyoRawPos",
            "MIT1",
            idx=0,
            cnv=float,
            comment="Mitutoyo 1 thread ring height (mm)",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "mitutoyoRawPos",
            "MIT2",
            idx=1,
            cnv=float,
            comment="Mitutoyo 2 thread ring height (mm)",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "mitutoyoRawPos",
            "MIT3",
            idx=2,
            cnv=float,
            comment="Mitutoyo 3 thread ring height (mm)",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "threadRingMotorPos",
            "TRPOS",
            idx=0,
            cnv=float,
            comment="Motor position of thread ring (mm)",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "scaleZeroPos",
            "TRZERO",
            idx=0,
            cnv=float,
            comment="Motor position where scale = 1",
            onFail="NaN",
        )
    )

    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "airmass",
            "ARMASS",
            idx=0,
            cnv=float,
            comment="Airmass",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "ffPower",
            "FFPWR",
            idx=0,
            cnv=str,
            comment="Flat field power on",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "ffCurrent",
            "FFI",
            idx=0,
            cnv=str,
            comment="Flat field current (A)",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "ffVoltage",
            "FFV",
            idx=0,
            cnv=str,
            comment="Flat field voltage (A)",
            onFail="NaN",
        )
    )

    return cards


def tccCards(models, cmd=None):
    """Return a list of fits Cards describing the TCC state."""

    cards = []

    tccDict = models["tcc"].keyVarDict

    try:
        objSys = tccDict["objSys"]
        objSysName = str(objSys[0])
    except Exception:
        objSysName = "unknown"
        if cmd:
            cmd.warn(
                'text="could not get objsys and epoch from tcc.objSys=%s"' % (objSys)
            )
    cards.append(makeCard(cmd, "OBJSYS", objSysName, "The TCC objSys"))

    if objSysName in ("None", "Mount", "Obs", "Phys", "Inst"):
        cards.append(makeCard(cmd, "RA", "NaN", "Telescope is not tracking the sky"))
        cards.append(makeCard(cmd, "DEC", "NaN", "Telescope is not tracking the sky"))
        cards.append(makeCard(cmd, "RADEG", "NaN", "Telescope is not tracking the sky"))
        cards.append(
            makeCard(cmd, "DECDEG", "NaN", "Telescope is not tracking the sky")
        )
        cards.append(makeCard(cmd, "SPA", "NaN", "Telescope is not tracking the sky"))
    else:
        cards.append(
            makeCardFromKey(
                cmd,
                tccDict,
                "objNetPos",
                "RA",
                cnv=_cnvPVTPosCard,
                idx=0,
                comment="RA of telescope boresight (deg)",
                onFail="NaN",
            )
        )
        cards.append(
            makeCardFromKey(
                cmd,
                tccDict,
                "objNetPos",
                "DEC",
                cnv=_cnvPVTPosCard,
                idx=1,
                comment="Dec of telescope boresight (deg)",
                onFail="NaN",
            )
        )
        cards.append(
            makeCardFromKey(
                cmd,
                tccDict,
                "objPos",
                "RADEG",
                cnv=_cnvPVTPosCard,
                idx=0,
                comment="RA of telescope pointing(deg)",
                onFail="NaN",
            )
        )
        cards.append(
            makeCardFromKey(
                cmd,
                tccDict,
                "objPos",
                "DECDEG",
                cnv=_cnvPVTPosCard,
                idx=1,
                comment="Dec of telescope pointing (deg)",
                onFail="NaN",
            )
        )
        cards.append(
            makeCardFromKey(
                cmd,
                tccDict,
                "spiderInstAng",
                "SPA",
                cnv=_cnvPVTPosCard,
                idx=0,
                comment="TCC SpiderInstAng",
                onFail="NaN",
            )
        )

    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "rotType",
            "ROTTYPE",
            cnv=str,
            idx=0,
            comment="Rotator request type",
            onFail="UNKNOWN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "rotPos",
            "ROTPOS",
            cnv=_cnvPVTPosCard,
            idx=0,
            comment="Rotator request position (deg)",
            onFail="NaN",
        )
    )

    offsets = (
        ("boresight", "BOREOFF", "TCC Boresight offset, deg", False),
        ("objArcOff", "ARCOFF", "TCC ObjArcOff, deg", False),
        ("calibOff", "CALOFF", "TCC CalibOff, deg", True),
        ("guideOff", "GUIDOFF", "TCC GuideOff, deg", True),
    )

    for tccKey, fitsName, comment, doRot in offsets:
        cards.append(
            makeCardFromKey(
                cmd,
                tccDict,
                tccKey,
                fitsName + "X",
                cnv=_cnvPVTPosCard,
                idx=0,
                comment=comment,
                onFail="NaN",
            )
        )
        cards.append(
            makeCardFromKey(
                cmd,
                tccDict,
                tccKey,
                fitsName + "Y",
                cnv=_cnvPVTPosCard,
                idx=1,
                comment=comment,
                onFail="NaN",
            )
        )
        if doRot:
            cards.append(
                makeCardFromKey(
                    cmd,
                    tccDict,
                    tccKey,
                    fitsName + "R",
                    cnv=_cnvPVTPosCard,
                    idx=2,
                    comment=comment,
                    onFail="NaN",
                )
            )

    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "axePos",
            "AZ",
            cnv=float,
            idx=0,
            comment="Azimuth axis pos. (approx, deg)",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "axePos",
            "ALT",
            cnv=float,
            idx=1,
            comment="Altitude axis pos. (approx, deg)",
            onFail="NaN",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "axePos",
            "IPA",
            cnv=float,
            idx=2,
            comment="Rotator axis pos. (approx, deg)",
            onFail="NaN",
        )
    )

    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "secFocus",
            "FOCUS",
            idx=0,
            cnv=float,
            comment="User-specified focus offset (um)",
            onFail="NaN",
        )
    )
    try:
        secOrient = tccDict["secOrient"]
        orientNames = ("piston", "xtilt", "ytilt", "xtran", "ytran", "zrot")
        for i in range(len(orientNames)):
            cards.append(
                makeCard(
                    cmd, "M2" + orientNames[i], float(secOrient[i]), "TCC SecOrient"
                )
            )
    except Exception as e:
        cmd.warn("text='failed to generate the SecOrient cards: %s'" % (e))

    try:
        primOrient = tccDict["primOrient"]
        orientNames = ("piston", "xtilt", "ytilt", "xtran", "ytran", "zrot")
        for i in range(len(orientNames)):
            cards.append(
                makeCard(
                    cmd, "M1" + orientNames[i], float(primOrient[i]), "TCC PrimOrient"
                )
            )
    except Exception as e:
        cmd.warn("text='failed to generate the PrimOrient cards: %s'" % (e))

    cards.append(
        makeCardFromKey(
            cmd,
            tccDict,
            "scaleFac",
            "SCALE",
            idx=0,
            cnv=float,
            comment="User-specified scale factor",
            onFail="NaN",
        )
    )
    return cards


def plateCards(models, cmd):
    """Return a list of fits Cards describing the plate/cartrige/pointing"""

    nameComment = "guider.cartridgeLoaded error"
    try:
        try:
            cartridgeKey = models["guider"].keyVarDict["cartridgeLoaded"]
        except Exception as e:
            nameComment = "Could not fetch guider.cartridgeLoaded keyword"
            cmd.warn('text="%s"' % nameComment)
            raise e

        cartridge, plate, pointing, mjd, mapping = cartridgeKey
        if (
            plate <= 0
            or cartridge <= 0
            or mjd < 50000
            or mapping < 1
            or pointing == "?"
        ):
            cmd.warn(
                'text="guider cartridgeKey is not well defined: %s"'
                % (str(cartridgeKey))
            )
            nameComment = "guider cartridgeKey %s is not well defined" % (
                str(cartridgeKey)
            )
            name = "0000-00000-00"
        else:
            nameComment = "The name of the currently loaded plate"
            name = "%04d-%05d-%02d" % (plate, mjd, mapping)
    except Exception as e:
        nameComment += "-cartKeyExcept: %s" % e
        cartridge, plate, pointing, mjd, mapping = -1, -1, "?", -1, -1
        name = "0000-00000-00"

    try:
        survey = models["sop"].keyVarDict["survey"]
        plateType, surveyMode = survey
    except Exception as e:
        plateType = "sop.survey %s: %s" % (type(e).__name__, e)
        surveyMode = plateType

    cards = []
    cards.append(
        makeCardFromKey(
            cmd,
            models["guider"].keyVarDict,
            "version",
            "v_guider",
            comment="version of the current guiderActor",
            onFail="Unknown",
        )
    )
    cards.append(
        makeCardFromKey(
            cmd,
            models["sop"].keyVarDict,
            "version",
            "v_sop",
            comment="version of the current sopActor",
            onFail="Unknown",
        )
    )

    cards.append(makeCard(cmd, "NAME", name, nameComment))
    cards.append(makeCard(cmd, "PLATEID", plate, "The currently loaded plate"))
    cards.append(makeCard(cmd, "CARTID", cartridge, "The currently loaded cartridge"))
    cards.append(
        makeCard(cmd, "MAPID", mapping, "The mapping version of the loaded plate")
    )
    cards.append(
        makeCard(cmd, "POINTING", pointing, "The currently specified pointing")
    )
    cards.append(
        makeCard(
            cmd,
            "PLATETYP",
            plateType,
            "Type of plate (e.g. BOSS, MANGA, " "APOGEE, APOGEE-MANGA)",
        )
    )

    # Only include survey mode when it has been specified.
    if surveyMode is not None and survey != "None":
        cards.append(
            makeCard(
                cmd,
                "SRVYMODE",
                surveyMode,
                "Survey leading this observation and its mode",
            )
        )

    return cards


def guiderCards(models, cmd):
    """Return a list of fits Cards describing the current guider status."""
    try:
        mangaDitherKey = models["guider"].keyVarDict["mangaDither"]
        mangaDither = mangaDitherKey[0]
    except BaseException:
        mangaDither = "??"

    try:
        decenterKey = models["guider"].keyVarDict["decenter"]
        expid, enabled, ra, dec, rot, focus, scale = decenterKey
    except BaseException:
        expid, enabled, ra, dec, rot, focus, scale = -1, "?", -1, -1, -1, -1, -1  # noqa

    cards = []
    cards.append(
        makeCard(cmd, "MGDPOS", mangaDither, "MaNGA dither position (C,N,S,E)")
    )
    cards.append(
        makeCard(cmd, "MGDRA", ra, "MaNGA decenter in RA, redundant with MGDPOS")
    )
    cards.append(
        makeCard(cmd, "MGDDEC", dec, "MaNGA decenter in Dec, redundant with MGDPOS")
    )
    # cards.append(makeCard(cmd, 'SEEING', name, 'Mean of guider seeing'))
    # cards.append(makeCard(cmd, 'TRANSPAR', name, 'Mean of guider transparancy'))
    return cards


def _cnvListCard(val, itemCnv=int):
    """Stupid utility to cons up a single string card from a list."""

    return " ".join([str(itemCnv(v)) for v in val])


def _cnvPVTPosCard(pvt, atTime=None):
    try:
        return pvt.getPos()
    except BaseException:
        return numpy.nan


def _cnvPVTVelCard(pvt):
    try:
        return pvt.getVel()
    except BaseException:
        return numpy.nan


def writeFits(
    cmd,
    hdu,
    directory,
    filename,
    doCompress=False,
    chmod=0o444,
    checksum=True,
    caller="",
    output_verify="warn",
):
    """
    Write a fits hdu to a fits file: directory/filename[.gz].

    Uses a named temporary file to write a fits file (potentially gzipped),
    (mostly) guaranteeing that the expected file name won't exist unless it
    really did get written.

    Args:
        cmd: provides debug, inform, warn, for logging (usually actorcore.Command instance).
        hdu: the fits HDU to write.
        directory: the directory (sans file) to write to.
        filename: the filename (sans directory) to write to.
        doCompress: gzip compressed with .gz extension.
        chmod: the mode you want the file to have (444 = all readonly).
        checksum: compute and save the checksum inside the file.
        caller: name of the calling object, for logging.
        output_verify: what to do about things that violate the FITS standard.

    Returns:
        The full name of the file that was eventually written.
    """

    outName = "XXX-%s" % (filename)
    suffix = ".gz" if doCompress else ""
    # to help with spacing out later string formatting:
    if caller != "":
        caller += " "
    try:
        if cmd is not None:
            cmd.inform(
                'text="writing %sFITS files for %s (%d threads)"'
                % (caller, filename, threading.active_count())
            )
        else:
            logging.info(
                "writing %sFITS files for %s (%d threads)"
                % (caller, filename, threading.active_count())
            )

        # Make a temp file, then move it into place once done.
        # If something horrific happens, we'll still have a semi-reasonable
        # filename, but it won't collide with anything else.
        # We can us mode 'wb' here, because we close the file after reading,
        # and the tempfile means it has a unique name, and will not already exist.
        tempFile = tempfile.NamedTemporaryFile(
            dir=directory, mode="wb", suffix=suffix, prefix=filename + ".", delete=False
        )
        tempName = tempFile.name

        if doCompress:
            outName = os.path.join(directory, filename)
            if filename[-3:] != ".gz":
                outName += ".gz"
            tempFile = gzip.GzipFile(
                fileobj=tempFile, filename=filename, mode="wb", compresslevel=4
            )
        else:
            outName = os.path.join(directory, filename)

        logging.info("Writing %s (via %s)" % (outName, tempName))
        hdu.writeto(tempFile, checksum=checksum, output_verify=output_verify)
        tempFile.flush()
        os.fsync(tempFile.fileno())
        os.fchmod(tempFile.fileno(), chmod)
        del tempFile

        logging.info("Renaming %s to %s" % (tempName, outName))
        os.rename(tempName, outName)
        logging.info("wrote %s" % (outName))
        if cmd is not None:
            cmd.inform('text="wrote %s"' % (outName))
    except Exception as e:
        if cmd is not None:
            cmd.warn('text="FAILED to write %sfile %s: %s"' % (caller, outName, e))
        else:
            logging.warn("FAILED to write %sfile %s: %s" % (caller, outName, e))
        raise
    else:
        return outName
