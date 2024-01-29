from amaranth import *
from amaranth.lib.coding import *
import numpy as np
from numpy import log2, sin, uint32, float64, power
tau = 2*np.pi

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

# FIXME:  The latest Amaranth documentation says to use Component
# instead of Elaboratable directly.
class ToneGenerator(Elaboratable):
    """

    """
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
        base_f0 = power(2, i+4)
        n_harmonics = np.floor(18000/base_f0)
        # Generate 1024 samples normalized to 1/2 waveform (hence /2*tau))
        # and including all harmonics up to 18kHz
        h = np.arange(1, n_harmonics+1)
        temp_ramp_tables[i] = np.sum(sin(h * base_f0 / (2*tau)) / h)

    # compress peak-to-peak relative to the largest amplitude
    temp_ramp_tables /= np.max(temp_ramp_tables)
    # convert to positive half of unsigned 24-bit range
    #ramp_tables = [Const(x, unsigned(23)) for x in temp_ramp_tables*(power(2,23) - 1).astype(uint32)]
    ramp_tables = [
                   [Const(x, unsigned(23)) for x in temp_ramp_tables[y]*(power(2,23) - 1).astype(uint32)]
                   for y in range(0,8)
                  ]
    del temp_ramp_tables

    def __init__(self,
                 channels: int = 3,
                 sample_rate: int = 96000,
                 multiplier_delay: int = 1):
        self._multiplier_delay = multiplier_delay
        self._channels = channels
        self.clk = Signal(1)
        self.update = Signal(1)
        # LSB to MSB:
        #   - phase_reset
        #   - enable
        #   - phase_increment
        #   - duty_cycle
        #   - lfo
        #   - lfo_offset
        # phase_increment and lfo_offset use the same data lines
        self.wr = Signal(6)
        self.channel_select = Signal(np.ceil(log2(channels)))
        self.phase_reset = Signal(1)
        # Register configuration
        self.enable = Signal(2)
        self.phase_increment = Signal(24)
        self.lfo_offset = self.phase_increment
        self.duty_cycle = Signal(8)
        self.lfo = Signal(2)
        # Configuration registers
        self.register_file = [ToneGeneratorRegisterFile() for x in range(0, channels)]

        # Output is 24-bit signed integer
        self.output = signed(24)

    def elaborate(self, platform) -> Module:
        m = Module()

        m.d.comb += m.d.sync.clk.eq(self.clk)

        # Valid states and transitions
        #
        # Start:
        #   Waiting for update signal.
        #   update == 1 -> Updating
        # Updating:
        #   Iterating through channels to update phase
        #   (last channel) -> Start
        with m.FSM():
            with m.State("Start"):
                with m.If(self.update):
                    pass

        # Sample update state machine
        # f(b) = base sample from duty cycle offset, i.e. Dry 2 when
        #        phase = 0
        #
        # Start:
        #   Waiting for sample update signal.
        #   sample_update[0] == 1 -> Dry 1
        # Dry 1:
        #   Channel dry enabled:
        #     Fetch two adjacent samples from look-up table.
        #     -> Dry 2
        #   Else:
        #     Clear dry sample register.
        #     -> Wet 1
        # Dry 2:
        #   Interpolate between two samples, store to register.
        #   Fetch two adjacent samples for f(b)
        #   Duty cycle % 0.5 != 0 -> Dry 3
        #   Wet enabled -> Wet 1
        # Dry 3:
        #   Interpolate between two samples, sum with register.
        #   Fetch two adjacent samples for f(w+b)
        #   -> Dry 4
        # Dry 4:
        #   Interpolate between two samples, sum with register.
        #   -> Wet 1
        # Wet 1:
        #   Channel wet enabled:
        #     Fetch two adjacent samples from look-up table for the
        #     LFO-modulated waveform.
        #     -> Wet 2
        #   Else:
        #     Increment channel
        #     sample_update[-1] == 1 -> Start
        #     -> Dry 1
        # Wet 2:
        #   
        return m

class ToneGeneratorRegister:

    def __init__(self):
        self._enable = Signal(2)
        self._phase = Signal(24)
        self._phase_increment = Signal(24)
        self._duty_cycle = Signal(8)
        self._lfo = Signal(2)
        self._lfo_offset = Signal(24)
