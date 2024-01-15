from amaranth import *
from amaranth.lib.coding import *
import numpy as np
from numpy import log2, sin, uint32, float64, power, pi
tau = 2*pi

# Build 8 look-up tables from 16Hz to 2048Hz
#
# XXX:  Turn this into a dual-port ROM module?  Integrate into a
# combined interpolator so the tone generator can request a 24-bit
# sample address and receive a value?
#
# Look-up tables are calculated in double-precision float64, then
# scaled to a maximum peak of 1.0 using the largest sample across all
# tables.  This keeps each specific harmonic component at the same
# amplitude.
#
# The finished tables are scaled to 24-bit integer and stored in an
# unsigned 32-bit integer.  Samples are one-half period and range
# entirely between 0 and 1; after completing a half-period, the same
# samples are played back in reverse and negated to make a full period.
temp_ramp_tables = np.empty((8,1024), dtype=float64)

for i in range(0,8):
    waveform = []
    base_f0 = power(2, i+4)
    n_harmonics = np.floor(18000/base_f0)
    # Generate 1024 samples normalized to 1/2 waveform (hence /2*tau))
    # and including all harmonics up to 18kHz
    h = np.arange(1, n_harmonics+1)
    temp_ramp_tables[i] = np.sum(sin(h * base_f0 / (2*tau)) / h)

# compress peak-to-peak relative to the largest amplitude
temp_ramp_tables /= np.max(temp_ramp_tables)
# convert to 24-bit 
ramp_tables = temp_ramp_tables*power(2,23).astype(uint32)
del temp_ramp_tables

# Mipmapped tone generator
#
# Uses 8 tables of ramps, 24 bit.
#
# Triangle is generated using the naive generator.  With its high
# rolloff rate, generation at 96kHz sample rate and filtering works
# exceedingly well.
#
# The enable register sets either dry (1), vibrato (2), or both (3)
# to emulate a chorus effect.  The corresponding LFO is read by the
# control unit, then written into the lfo_offset register for the
# specific channel.
#
# The envelope controller, not the tone generator, handles the
# amplitude.

class ToneGenerator(Elaboratable):
    """

    """
    def __init__(self,
                 channels: int = 3,
                 sample_rate: int = 96000,
                 multiplier_delay: int = 1):
        self._multiplier_delay = multiplier_delay
        self._channels = channels
        self.clk = Signal(1)
        # LSB to MSB:
        #   - phase_reset
        #   - enable
        #   - phase_increment
        #   - duty_cycle
        #   - lfo
        #   - lfo_offset
        # phase_increment and lfo_offset use the same data lines
        self.wr = Signal(1)
        self.channel_select = Signal(np.ceil(log2(channels)))
        self.phase_reset = Signal(1)
        # Register configuration
        self.enable = Signal(2)
        self.phase_increment = Signal(24)
        self.lfo_offset = self.phase_increment
        self.duty_cycle = Signal(8)
        self.lfo = Signal(2)
        # Configuration registers
        self._enable = []
        self._phase = []
        self._phase_increment = []
        self._duty_cycle = []
        self._lfo = []
        self._lfo_offset = []
        for x in range(0, channels):
            self._enable.append(Signal(2))
            self._phase.append(Signal(24))
            self._phase_increment.append(Signal(24))
            self._duty_cycle.append(Signal(8))
            self._lfo.append(Signal(2))
            self._lfo_offset.append(Signal(24))

    def elaborate(self, platform) -> Module:
        m = Module()

        return m

