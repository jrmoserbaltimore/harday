from amaranth import *
from amaranth.lib.coding import *
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
    def __init__(self, count: int, multiplier_delay: int = 1):
        assert (count > 0), "count must be greater than zero"
        self.count = count
        self.multiplier_delay = multiplier_delay
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
        self.SineDelay = []
        self.CosineDelay = []
        for x in range(0,int):
            self.PhaseIncrement.append(Signal(16))
            self.PhaseAccumulator.append(Signal(16))
            self.Waveform.append(Signal(2))
            self.Direction.append(Signal(1))
            self.Reset.append(Signal(1))
            self.SineDelay.append(Signal(16))
            self.CosineDelay.append(Signal(16))
        # Updating state tracks which oscillator is being updated 
        self.Updating = Signal(count)

    def elaborate(self, platform) -> Module:
        m = Module()
        
        # Data for sine and cosine update, the index of the register to
        # update, and whether to update.  For pipelining updates.
        SineUpdate = [Signal(16) for x in range(0,multiplier_delay)]
        CosineUpdate = [Signal(16) for x in range(0,multiplier_delay)]
        SineUpdateIndex = [Signal(ceil(log2(self.count))) for x in range (0,multiplier_delay)]
        SineUpdateEnable = [Signal(1) for x in range (0,multiplier_delay)]
        
        # Update routine
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
        # Updating has a deterministic time cost; don't poke it rapidly
        with m.If(self.Update):
            m.d.sync += [
                    self.Updating.eq(1)
                ]
        with m.If(any(self.Updating)):
            # Get the index of the oscillator to update
            x = Signal(ceil(log2(count)))
            m.d.comb += x.eq(PriorityEncoder(count, self.Updating).o)
            # Increment the target oscillator
            m.d.sync += self.Updating.eq(self.Updating << 1)
            
            # Decode Waveform
            ramp = (self.Waveform[x] == 0)
            square = (self.Waveform[x] == 1)
            triangle = (self.Waveform[x] == 2)
            sine = (self.Waveform[x] == 3)
            PA = Signal(17)
            OutputPhase = Signal(16)
            NewDirection = Signal(1)
            # Sum to PA in the combinational domain, with the extra bit
            # for overflow
            m.d.comb += [
                PA.eq(self.PhaseAccumulator[x] +
                    mux(triangle,
                        self.PhaseIncrement[x] << 1,
                        self.PhaseIncrement[x]
                    )
                ),
                # Flip on overflow if triangle
                NewDirection.eq(self.Direction ^ (PA[16] & triangle))
            ]
            m.d.sync += [
                # Store new sum in phase accumulator
                self.PhaseAccumulator[x].eq(PA[0:15]),
                self.Direction.eq(NewDirection)
            ]
            ##########################
            # Update sine oscillator #
            ##########################
            # Put the multiplication, index, and enable in the pipeline
            m.d.sync += [
                SineUpdate[0].eq(CosineDelay[x] * PhaseIncrement[x]),
                CosineUpdate[0].eq(CosineDelay[x] * -PhaseIncrement[x]),
                SineUpdateIndex[0].eq(x),
                SineUpdateEnable[0].eq(1)
            ]
        
        # Delay the multiplication a number of cycles for the
        # synthesizer to pipeline the multiplier
        for i in range(1,multiplier_delay):
            m.d.sync += [
                SineUpdate[i].eq(SineUpdate[i-1]),
                CosineUpdate[i].eq(CosineUpdate[i-1]),
                SineUpdateIndex[i].eq(SineUpdateIndex[i-1]),
                SineUpdateEnable[i].eq(SineUpdateEnable[i-1])
            ]
        
        # If an update is at the end of the pipeline, add the results
        # to z^-1 for sine and cosine
        with m.If(SineUpdateEnable[multiplier_delay-1]):
            i = multiplier_delay-1
            idx = (SineUpdateIndex[i])
            m.d.sync += [
                SineDelay[idx].eq(SineUpdate[i] + SineDelay[idx]),
                CosineDelay[idx].eq(CosineUpdate[i] + CosineDelay[idx])
            ]
        # Calculate output phase.  If Direction = 1, flip the waveform
        #m.d.comb += OutputPhase.eq((PA[0:15] ^ self.Direction.replicate(16))
        #                                 + self.Direction)
                
                
        
