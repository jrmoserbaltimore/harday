from amaranth import *
from amaranth.lib.coding import *
from numpy import log2, ceil

# Uses differential polynomials to generate trivial waveforms,
# including ramp, pulse, and triangle.
#
# This only generates ramps, and each waveform generates two ramps.
# Rather than a square or triangle polynomial, two polinomials are
# generated, summed, and then differenced to produce the alias-
# suppressed pulse wave; the last stage of differencing is skipped to
# produce an integrated pulse wave, which is a triangle.
#
# Questions:
#
#   - How to make generic?  We want to sum 4 polynomials and then
#     difference the result.
#   - What configuration does this part hold?
class DifferentialPolynomialWaveform(Elaboratable):
    """DPW
    """
    def __init__(self, count: int, multiplier_delay: int = 1,
                 precision: int = None):
        assert (count > 0), "count must be greater than zero"
        self.count = count
        self.multiplier_delay = multiplier_delay
        self.precision = precision
        self.Clk = Signal(1)
        # When Update becomes high, an internal state machine
        # updates each counter in sequence.
        self.Update = Signal(1)
        self.Address = Signal(ceil(log2(count)))
        self.DataOut = Signal(precision)
        self.DataIn = Signal(precision)
        self.WriteEnable = Signal(1)
        self.WriteSelect = Signal(1)
        self.WriteMask = Signal(4)
        # Create register file
        self.PhaseIncrement = []
        self.PhaseAccumulator = []
        self.Waveform = []
        self.Direction = []
        for x in range(0,int):
            self.PhaseIncrement.append(Signal(16))
            self.PhaseAccumulator.append(Signal(16))
            self.Waveform.append(Signal(2))
            self.Direction.append(Signal(1))
        # Updating state tracks which oscillator is being updated 
        self.Updating = Signal(count)

    def elaborate(self, platform) -> Module:
        m = Module()
