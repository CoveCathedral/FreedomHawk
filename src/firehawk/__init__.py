"""Firehawk Accessible Controller.

An accessible, screen-reader-first Windows application that controls a Line 6
Firehawk FX guitar multi-effects pedal directly over its Bluetooth serial link,
independent of Line 6's discontinued mobile app and cloud.

The package is organised into the same layers found in the original app:

* :mod:`firehawk.model`      -- the tone model (models, parameters, ranges, symbols)
* ``firehawk.transport``     -- raw byte I/O over the paired COM/RFCOMM port (later)
* ``firehawk.protocol``      -- wire framing + parameter encoding/decoding (later)
* ``firehawk.ui``            -- the accessible wxPython interface (later)
"""

__version__ = "0.1.0"
