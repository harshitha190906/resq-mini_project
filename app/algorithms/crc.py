"""
ResQNet — app/algorithms/crc.py
================================
Cyclic Redundancy Check (CRC) error-detection for emergency packet
transmission, implemented using pure binary polynomial division (XOR).

Background
----------
CRC works by treating a bitstring as a binary polynomial, dividing it by a
agreed-upon **generator polynomial**, and appending the remainder (the CRC
checksum) to the original data.  The receiver performs the same division; a
zero remainder means no errors were detected.

Terminology
-----------
* **Dataword** — the raw bits to be protected (e.g. ``"1101011011"``).
* **Generator polynomial** — a fixed bitstring whose leftmost and rightmost
  bits are always ``'1'`` (e.g. CRC-4: ``"10011"``).
* **Codeword** — dataword + CRC checksum transmitted over the channel.
* **Syndrome** — the remainder obtained by dividing a received codeword by
  the generator; a non-zero syndrome signals a detected error.

Supported presets
-----------------
``CRCPreset`` enumerates common generator polynomials so callers do not need
to remember the bit-strings:

+---------+-------------------+
| Preset  | Generator         |
+=========+===================+
| CRC4    | ``10011``         |
+---------+-------------------+
| CRC8    | ``100000111``     |
+---------+-------------------+
| CRC16   | ``11000000000000101`` |
+---------+-------------------+
| CRC_CCITT | ``10001000000100001`` |
+---------+-------------------+
| CUSTOM  | user-supplied     |
+---------+-------------------+

Usage
-----
::

    from app.algorithms.crc import CRCEngine, CRCPreset

    engine   = CRCEngine("10011")           # CRC-4 generator
    codeword = engine.generate("1101011011")

    result   = engine.verify(codeword.codeword)
    print(result.valid)           # True

    # Inject 1 bit-error and verify
    bad    = engine.inject_errors(codeword.codeword, positions=[3])
    result = engine.verify(bad.corrupted)
    print(result.valid)           # False (error detected)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations / presets
# ─────────────────────────────────────────────────────────────────────────────

class CRCPreset(str, Enum):
    """Common CRC generator polynomials represented as binary strings."""
    CRC4      = "10011"
    CRC8      = "100000111"
    CRC16     = "11000000000000101"
    CRC_CCITT = "10001000000100001"
    CUSTOM    = "CUSTOM"           # user supplies their own polynomial


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CRCGenerateResult:
    """
    Output of :meth:`CRCEngine.generate`.

    Attributes
    ----------
    dataword : str
        The original input bitstring.
    generator : str
        The generator polynomial used.
    padded_dataword : str
        Dataword with ``(len(generator) - 1)`` zero bits appended before
        the division step.
    remainder : str
        The CRC checksum (binary string of length ``len(generator) - 1``).
    codeword : str
        ``dataword + remainder`` — the bitstring to transmit.
    division_steps : list[dict]
        Step-by-step trace of the XOR division for educational display.
    """
    dataword:        str
    generator:       str
    padded_dataword: str
    remainder:       str
    codeword:        str
    division_steps:  List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dataword":        self.dataword,
            "generator":       self.generator,
            "padded_dataword": self.padded_dataword,
            "remainder":       self.remainder,
            "codeword":        self.codeword,
            "division_steps":  self.division_steps,
        }


@dataclass
class CRCVerifyResult:
    """
    Output of :meth:`CRCEngine.verify`.

    Attributes
    ----------
    received : str
        The bitstring that was checked.
    generator : str
        Generator polynomial used.
    syndrome : str
        Remainder of ``received ÷ generator``.
    valid : bool
        ``True`` iff ``syndrome == '000…'`` (all zeros → no error detected).
    division_steps : list[dict]
        Step-by-step XOR trace.
    """
    received:       str
    generator:      str
    syndrome:       str
    valid:          bool
    division_steps: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "received":       self.received,
            "generator":      self.generator,
            "syndrome":       self.syndrome,
            "valid":          self.valid,
            "division_steps": self.division_steps,
        }


@dataclass
class CRCErrorInjectionResult:
    """
    Output of :meth:`CRCEngine.inject_errors`.

    Attributes
    ----------
    original : str
        The bitstring before error injection.
    corrupted : str
        The bitstring after flipping the requested bits.
    flipped_positions : list[int]
        0-based indices of bits that were flipped.
    num_errors : int
        ``len(flipped_positions)``
    """
    original:          str
    corrupted:         str
    flipped_positions: List[int]
    num_errors:        int

    def to_dict(self) -> dict:
        return {
            "original":          self.original,
            "corrupted":         self.corrupted,
            "flipped_positions": self.flipped_positions,
            "num_errors":        self.num_errors,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────

class CRCEngine:
    """
    CRC generation and verification engine.

    Parameters
    ----------
    generator : str or CRCPreset
        The generator polynomial as a binary string (e.g. ``"10011"``),
        **or** a :class:`CRCPreset` value.  Must start and end with ``'1'``
        and be at least 2 bits long.

    Examples
    --------
    >>> engine = CRCEngine("10011")
    >>> result = engine.generate("1101011011")
    >>> result.codeword
    '11010110111110'
    """

    def __init__(self, generator: str | CRCPreset) -> None:
        if isinstance(generator, CRCPreset):
            if generator == CRCPreset.CUSTOM:
                raise ValueError(
                    "CRCPreset.CUSTOM requires you to supply the generator "
                    "polynomial as a string, not the enum value."
                )
            generator = generator.value
        self._validate_generator(generator)
        self._generator: str = generator

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def generator(self) -> str:
        """The generator polynomial in use."""
        return self._generator

    @property
    def checksum_length(self) -> int:
        """Number of CRC bits appended to each dataword."""
        return len(self._generator) - 1

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(self, dataword: str) -> CRCGenerateResult:
        """
        Compute the CRC checksum for *dataword* and return the codeword.

        Parameters
        ----------
        dataword : str
            Binary string of ``'0'`` and ``'1'`` characters.  Must be
            non-empty.

        Returns
        -------
        CRCGenerateResult
        """
        self._validate_bitstring(dataword, "dataword")

        # Append (n-1) zeros where n = len(generator)
        padded = dataword + "0" * self.checksum_length
        remainder, steps = self._xor_divide(padded, self._generator)

        # Remainder is left-padded with zeros to exactly checksum_length bits
        remainder = remainder.zfill(self.checksum_length)

        return CRCGenerateResult(
            dataword=dataword,
            generator=self._generator,
            padded_dataword=padded,
            remainder=remainder,
            codeword=dataword + remainder,
            division_steps=steps,
        )

    def verify(self, received: str) -> CRCVerifyResult:
        """
        Check whether *received* (dataword + CRC) is error-free.

        Parameters
        ----------
        received : str
            The full codeword as a binary string.

        Returns
        -------
        CRCVerifyResult
            ``result.valid`` is ``True`` iff the syndrome is all zeros.
        """
        self._validate_bitstring(received, "received")
        if len(received) < len(self._generator):
            raise ValueError(
                f"received bitstring (len {len(received)}) is shorter than "
                f"the generator (len {len(self._generator)})."
            )

        syndrome, steps = self._xor_divide(received, self._generator)
        syndrome = syndrome.zfill(self.checksum_length)
        valid = all(b == "0" for b in syndrome)

        return CRCVerifyResult(
            received=received,
            generator=self._generator,
            syndrome=syndrome,
            valid=valid,
            division_steps=steps,
        )

    def inject_errors(
        self,
        bitstring: str,
        positions: List[int],
    ) -> CRCErrorInjectionResult:
        """
        Flip bits at specified 0-based *positions* to simulate transmission
        errors.

        Parameters
        ----------
        bitstring : str
            The binary string to corrupt (typically a codeword).
        positions : list[int]
            0-based indices of bits to flip.  Duplicates are ignored.
            All indices must be within ``[0, len(bitstring) - 1]``.

        Returns
        -------
        CRCErrorInjectionResult
        """
        self._validate_bitstring(bitstring, "bitstring")
        unique_positions = sorted(set(positions))
        for p in unique_positions:
            if p < 0 or p >= len(bitstring):
                raise IndexError(
                    f"Bit position {p} is out of range for a "
                    f"{len(bitstring)}-bit string."
                )

        bits = list(bitstring)
        for p in unique_positions:
            bits[p] = "1" if bits[p] == "0" else "0"

        return CRCErrorInjectionResult(
            original=bitstring,
            corrupted="".join(bits),
            flipped_positions=unique_positions,
            num_errors=len(unique_positions),
        )

    # ── Core XOR division ─────────────────────────────────────────────────────

    @staticmethod
    def _xor_divide(dividend: str, divisor: str) -> tuple[str, List[dict]]:
        """
        Perform binary XOR (modulo-2) polynomial long division.

        Parameters
        ----------
        dividend : str
            The padded dataword (or received codeword).
        divisor : str
            The generator polynomial.

        Returns
        -------
        (remainder, steps)
            *remainder* — the final binary remainder string.
            *steps*     — list of dicts recording each XOR step.
        """
        n       = len(divisor)
        current = list(dividend)   # work on a mutable copy
        steps:  List[dict] = []
        step_num = 0

        for i in range(len(dividend) - n + 1):
            # Only divide when the leading bit is '1'
            if current[i] == "1":
                step_num += 1
                before_xor = "".join(current)

                for j in range(n):
                    current[i + j] = (
                        "0" if current[i + j] == divisor[j] else "1"
                    )

                steps.append({
                    "step":      step_num,
                    "position":  i,
                    "before":    before_xor,
                    "xor_with":  divisor.ljust(len(dividend), " "),
                    "after":     "".join(current),
                })

        # The remainder is the last (n-1) bits
        remainder = "".join(current[-(n - 1):])
        return remainder, steps

    # ── Validation helpers ────────────────────────────────────────────────────

    @staticmethod
    def _validate_generator(gen: str) -> None:
        if len(gen) < 2:
            raise ValueError("Generator polynomial must be at least 2 bits long.")
        if not all(b in "01" for b in gen):
            raise ValueError("Generator polynomial must contain only '0' and '1'.")
        if gen[0] != "1" or gen[-1] != "1":
            raise ValueError(
                "Generator polynomial must start and end with '1'."
            )

    @staticmethod
    def _validate_bitstring(bits: str, name: str) -> None:
        if not bits:
            raise ValueError(f"'{name}' must not be empty.")
        if not all(b in "01" for b in bits):
            raise ValueError(
                f"'{name}' must contain only '0' and '1'; got: {bits!r}"
            )
