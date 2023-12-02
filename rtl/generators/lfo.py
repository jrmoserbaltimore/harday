from amaranth import *
from amaranth.lib.coding import *
from numpy import log2, ceil

# low-frequency oscillator
#
# The LFO produces an output between -1 and 1; however, it tracks phase
# internally normalized to [0,tau), where PhaseAccumulator rolls over
# at 1, unsigned.  Calculating the output is slightly involved:
#
# Ramps:
#   Subtract 0.5 from the PhaseAccumulator and multiplying by 2.
#
# Square:
#   The MSB indicates 1 or -1.
#
# Triangle:
#   Calculate a ramp.  Multiply the ramp by -1 if Direction=1.
#
# Sine is handled completely differently.
#
# FIXME:  correct the outputs as per above.  This requires
# figuring out how the chip will handle data internally (i.e.
# integer [0,2^n), fixed point?)

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
        self.SineDelay = []
        self.CosineDelay = []
        for x in range(0,int):
            self.PhaseIncrement.append(Signal(16))
            self.PhaseAccumulator.append(Signal(16))
            self.Waveform.append(Signal(2))
            self.Direction.append(Signal(1))
            self.SineDelay.append(Signal(16))
            self.CosineDelay.append(Signal(16))
        # Updating state tracks which oscillator is being updated 
        self.Updating = Signal(count)

    def elaborate(self, platform) -> Module:
        m = Module()

        ##################
        # Update routine #
        ##################
        # For non-sine:
        #   - Add PhaseIncrement to PhaseAccumulator
        #     - If triangle, add PhaseIncrement<<1 instead
        #   - If triangle, set Direction to PhaseAccumulator overflow
        # Updating has a deterministic time cost; poke it exactly once
        # between generating a single sample on all tone generators.
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
            ramp = _is_ramp(self.Waveform[x])
            square = _is_square(self.Waveform[x])
            triangle = _is_triangle(self.Waveform[x])
            sine = _is_sine(self.Waveform[x])
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
        # The sine oscillator is much simpler:  it's a resonating
        # state variable filter.

        # Data for sine and cosine update, the index of the register to
        # update, and whether to update.  For pipelining updates.
        SineUpdate = [Signal(16) for x in range(0,multiplier_delay)]
        CosineUpdate = [Signal(16) for x in range(0,multiplier_delay)]
        SineUpdateIndex = [Signal(ceil(log2(self.count))) for x in range (0,multiplier_delay)]
        SineUpdateEnable = [Signal(1) for x in range (0,multiplier_delay)]

        with m.If(any(self.Updating)):
            # Put the multiplication, index, and enable in the pipeline
            m.d.sync += [
                SineUpdate[0].eq(CosineDelay[x] * PhaseIncrement[x]),
                CosineUpdate[0].eq(CosineDelay[x] * -PhaseIncrement[x]),
                SineUpdateIndex[0].eq(x),
                SineUpdateEnable[0].eq(1)
            ]
        with m.Else():
            # When not updating, we need to clear the sine oscillator
            # update pipeline or it will continuously carry out the
            # final addition.
            #
            # Only the enable signal matters, leave the rest alone.
            m.d.sync += [
                #SineUpdate[0].eq(0),
                #CosineUpdate[0].eq(0),
                #SineUpdateIndex[0].eq(0),
                SineUpdateEnable[0].eq(0)
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

        #######
        # I/O #
        #######
        # FIXME:  Deuglify these long lines
        # Always put the waveform for the current address on DataOut
        #   - Store PhaseAccumulator on DataOut, as:
        #     Direction   0   1
        #     Ramp:       +   +
        #     Triangle:   +   -
        #     Square:     MSB ~MSB
        with m.If(_is_sign(self.Waveform[self.Address])):
            m.d.sync += self.DataOut.eq(self.SineDelay[self.Address])
        with m.Elif(_is_square(self.Waveform[self.Address])):
            # Square, take the MSB, XOR with direction, and shift to
            # MSB.  Direction inverts duty cycle.
            m.d.sync += self.DataOut.eq(
                        (self.PhaseAccumulator[self.Address][15] ^ self.Direction[Address]) << 15
                    )
        with m.Else():
            # Ramps and triangles invert if Direction is 1; triangles
            # invert Direction when they overflow, ramps can slope up
            # or down
            m.d.sync += self.DataOut.eq(
                            (self.PhaseAccumulator[self.Address] ^ self.Direction[Address].replicate(16))
                            + self.Direction[Address]
                        )

        with m.If(self.WriteEnable):
            # Select either the PhaseIncrement register or the
            # Waveform, Direction, and Reset command
            with m.Switch(self.WriteSelect):
                with m.Case(0):
                    m.d.sync += self.PhaseIncrement[self.Address].eq(self.DataIn)
                with m.Case(1):
                    m.d.sync += self.Waveform[self.Address].eq(
                            (self.Waveform[self.Address] & ~self.WriteMask[3:2])
                            | (self.DataIn[3:2] & self.WriteMask[3:2])
                        )
                    with m.If(self.WriteMask[1]):
                        m.d.sync += self.Direction[self.Address].eq(self.DataIn[1])
                    # Reset signal
                    with m.if(self.WriteMask[0] & self.DataIn[0]):
                        m.d.sync += self.PhaseAccumulator[self.Address].eq(0)
                        # Clear the sine wave.  Move tau/2 forward if
                        # direction is 1 (i.e. reverse sine).
                        #
                        # If we're setting Direction, then use the
                        # incoming value; else use the registered value
                        with m.Switch(mux(self.WriteMask[1], self.DataIn[1],
                                          self.Direction[self.Address])):
                            with m.Case(0):
                                m.d.sync += [
                                    self.SineDelay[self.Address].eq(0),
                                    self.CosineDelay[self.Address].eq(1)
                                ]
                            with m.Case(1):
                                m.d.sync += [
                                    self.SineDelay[self.Address].eq(0),
                                    self.CosineDelay[self.Address].eq(-1)
                                ]
        return m

    def _is_ramp(self, signal: Signal(2)):
        return (signal == 0)

    def _is_square(self, signal: Signal(2)):
        return (signal == 1)

    def _is_triangle(self, signal: Signal(2)):
        return (signal == 2)

    def _is_sine(self, signal: Signal(2)):
        return (signal == 3)