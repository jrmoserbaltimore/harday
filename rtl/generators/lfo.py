from amaranth import *
from numpy import log2, ceil
# low-frequency oscillator

class LFO(Elaboratable):
    """LFO
    Produces a low-frequency oscillator with (count) registers.
    Update:  State machine updates all oscillators
    Address:  Select the LFO to access.
    WriteSelect:  Write to PhaseIncrement(0) or others (1).
       When WriteSelect=1, the lower 4 bits of DataIn
       represent Waveform, Direction, and Reset, from MSB to
       LSB.
    WriteMask:  When WriteSelect=1, the new values written to
       Waveform, Direction, and Reset as WFDR=Signal(4) is
       (DataIn[3:0] & WriteMask) | (WFDR & ~WriteMask).
    """
    def __init__(self, count: int):
        assert (count > 0), "count must be greater than zero"
        self.Clk = Signal(1)
        # When Update becomes high, an internal state machine
        # updates each counter in sequence.
        self.Update = Signal(1)
        self.Address = Signal(ceil(log2(count)))
        self.DataOut = Signal(16)
        self.DataIn = Signal(16)
        self.WriteEnable = Signal(1)
        self.WriteSelect = Signal(1)
        self.WriteMask = Signal(4)
        # Create register file
        self.PhaseIncrement = []
        self.PhaseAccumulator = []
        self.Waveform = []
        self.Direction = []
        self.Reset = []
        for x in range(0,int):
            self.PhaseIncrement.append(Signal(16))
            self.PhaseAccumulator.append(Signal(17))
            self.Waveform.append(Signal(2))
            self.Direction.append(Signal(1))
            self.Reset.append(Signal(1))

    def elaborate(self, platform) -> Module:
        m = Module()
        
        # For non-sine:
        #   - Store PhaseAccumulator on DataOut if requested, as:
        #
        #     Direction   0  1
        #     Ramp:       +  +
        #     Triangle:   +  -
        #     Square:     0  1
        #   - Add PhaseIncrement to PhaseAccumulator
        #     - If triangle, add PhaseIncrement<<1 instead
        #   - If triangle, set Direction to PhaseAccumulator overflow
        #   - Add PhaseIncrement to PhaseAccumulator
        # For sine:
        #   - Set sin=0 cos=1; cos=-1 for Direction=1
        for x in range(0, len(PhaseIncrement))
        m.d.comb += [
            PhaseAccumulator[x].eq(PhaseAccumulator[x] +
                                    mux(Direction,
                                        ~PhaseIncrement[x]+1,
                                        PhaseIncrement[x])
                                   )
        ]
        
        