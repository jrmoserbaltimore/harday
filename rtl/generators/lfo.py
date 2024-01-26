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
    update:  State machine updates all oscillators
    address:  Select the LFO to access.
    write_select:  Write to phase_increment(0) or others (1).
       When write_select=1, the lower 4 bits of DataIn
       represent Waveform, Direction, and Reset, from MSB to
       LSB.
    write_mask:  When write_select=1, the new values written to
       Waveform, Direction, and Reset as WFDR=Signal(4) is
       (data_in[3:0] & write_mask) | (wfdr_buffer & ~write_mask).
    """
    def __init__(self, count: int, multiplier_delay: int = 1):
        assert (count > 0), "count must be greater than zero"
        self.count = count
        self.multiplier_delay = multiplier_delay
        self.clk = Signal(1)
        # When update becomes high, an internal state machine
        # updates each counter in sequence.
        self.update = Signal(1)
        self.address = Signal(ceil(log2(count)))
        self.data_out = Signal(16)
        self.data_in = Signal(16)
        self.write_enable = Signal(1)
        self.write_select = Signal(1)
        self.write_mask = Signal(4)
        # Create register file
        self.register_file = [LFORegisterFile() for x in range(0,count)]
        # Updating state tracks which oscillator is being updated 
        self.updating = Signal(count)

    def elaborate(self, platform) -> Module:
        m = Module()

        m.d.comb += m.d.sync.clk.eq(self.clk)

        osc = self.register_file
        ##################
        # Update routine #
        ##################
        # For non-sine:
        #   - Add PhaseIncrement to PhaseAccumulator
        #     - If triangle, add PhaseIncrement<<1 instead
        #   - If triangle, set Direction to PhaseAccumulator overflow
        # Updating has a deterministic time cost; poke it exactly once
        # between generating a single sample on all tone generators.
        
        # Data for sine and cosine update, the index of the register to
        # update, and whether to update.  For pipelining updates.
        sine_update = [Signal(16) for x in range(0,self.multiplier_delay)]
        cosine_update = [Signal(16) for x in range(0,self.multiplier_delay)]
        sine_update_index = [Signal(ceil(log2(self.count))) for x in range (0,self.multiplier_delay)]
        sine_update_enable = [Signal(1) for x in range (0,self.multiplier_delay)]

        # Update state machine
        with m.FSM():
            with m.State("Start"):
                with m.If(self.update):
                    m.d.sync += self.updating.eq(1)
                    m.next = "Updating"
                # When not updating, we need to clear the sine oscillator
                # update pipeline or it will continuously carry out the
                # final addition.
                #
                # Only the enable signal matters, leave the rest alone.
                m.d.sync += [
                    #SineUpdate[0].eq(0),
                    #CosineUpdate[0].eq(0),
                    #SineUpdateIndex[0].eq(0),
                    sine_update_enable[0].eq(0)
                ]
            with m.State("Updating"):
                # Get the index of the oscillator to update
                x = Signal(ceil(log2(self.count)))
                m.d.comb += x.eq(PriorityEncoder(self.count, self.updating).o)
                # Increment the target oscillator
                m.d.sync += self.updating.eq(self.updating << 1)
                with m.If(self.updating[-1] == 0):
                    m.next = "Start"

                # Decode Waveform
                PA = Signal(17)
                OutputPhase = Signal(16)
                NewDirection = Signal(1)
                # Sum to PA in the combinational domain, with the extra bit
                # for overflow
                m.d.comb += [
                    PA.eq(osc[x].phase_accumulator +
                        mux(osc[x].is_triangle(),
                            osc[x].phase_increment << 1,
                            osc[x].phase_increment
                        )
                    ),
                    # Flip on overflow if triangle
                    NewDirection.eq(osc[x].direction ^ (PA[16] & osc[x].is_triangle()))
                ]
                m.d.sync += [
                    # Store new sum in phase accumulator
                    osc[x].phase_accumulator.eq(PA[0:15]),
                    osc[x].direction.eq(NewDirection)
                ]

                ##########################
                # Update sine oscillator #
                ##########################
                # The sine oscillator is much simpler:  it's a resonating
                # state variable filter.

                # Put the multiplication, index, and enable in the pipeline.
                # Does not cause an update if reset signal has been sent
                m.d.sync += [
                    sine_update[0].eq(osc[x].cosine_delay * osc[x].phase_increment),
                    cosine_update[0].eq(osc[x].cosine_delay * -osc[x].phase_increment),
                    sine_update_index[0].eq(x),
                    sine_update_enable[0].eq(~self._is_resetting(x))
                ]
                # Also execute the WFDR buffer.
                m.d.sync += [
                    osc[x].waveform.eq(
                        (osc[x].waveform & ~osc[x].wfdr_mask[3:2])
                        | (osc[x].wfdr_buffer[3:2] & osc[x].wfdr_mask[3:2])
                    ),
                    # Clear the mask so these commands won't be executed
                    # again next update
                    osc[x].wfdr_mask.eq(0)
                ]
                with m.If(osc[x].wfdr_mask[1]):
                    m.d.sync += osc[x].direction.eq(osc[x].wfdr_buffer[1])
                # Reset signal
                with m.If(osc[x]._is_resetting()):
                    m.d.sync += self.phase_accumulator[x].eq(0)
                    # Clear the sine wave.  Move tau/2 forward if
                    # direction is 1 (i.e. reverse sine).
                    #
                    # If we're setting Direction, then use the
                    # incoming value; else use the registered value
                    m.d.sync += osc[x].sine_delay.eq(0)
                    with m.Switch(mux(osc[x].wfdr_mask[1], osc[x].wfdr_buffer[1],
                                      osc[x].direction)):
                        with m.Case(0):
                            m.d.sync += osc[x].cosine_delay.eq(1)
                        with m.Case(1):
                            m.d.sync += osc[x].cosine_delay.eq(-1)

        # Delay the multiplication a number of cycles for the
        # synthesizer to pipeline the multiplier
        for i in range(1,self.multiplier_delay):
            m.d.sync += [
                sine_update[i].eq(sine_update[i-1]),
                cosine_update[i].eq(cosine_update[i-1]),
                sine_update_index[i].eq(sine_update_index[i-1]),
                sine_update_enable[i].eq(sine_update_enable[i-1])
            ]
        
        # If an update is at the end of the pipeline, add the results
        # to z^-1 for sine and cosine
        with m.If(sine_update_enable[self.multiplier_delay-1]):
            i = self.multiplier_delay-1
            idx = (sine_update_index[i])
            m.d.sync += [
                osc[idx].sine_delay.eq(sine_update[i] + osc[idx].sine_delay),
                osc[idx].cosine_delay.eq(cosine_update[i] + osc[idx].cosine_dealy)
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
        with m.If(osc[self.address].is_sine()):
            m.d.sync += self.data_out.eq(osc[self.address].sine_delay)
        with m.Elif(osc[self.address].is_square()):
            # Square, take the MSB, XOR with direction, and shift to
            # MSB.  Direction inverts duty cycle.
            m.d.sync += self.data_out.eq(
                        (osc[self.address].phase_accumulator[15] ^ osc[self.address].direction) << 15
                    )
        with m.Else():
            # Ramps and triangles invert if Direction is 1; triangles
            # invert Direction when they overflow, ramps can slope up
            # or down
            m.d.sync += self.data_out.eq(
                            (osc[self.address].phase_accumulator ^ osc[self.address].direction.replicate(16))
                            + osc[self.address].direction
                        )
        with m.If(self.write_enable):
            # Select either the PhaseIncrement register or the
            # Waveform, Direction, and Reset command
            with m.Switch(self.write_select):
                with m.Case(0):
                    m.d.sync += osc[self.address].phase_increment.eq(self.data_in)
                # Buffer WFDR for application during update
                with m.Case(1):
                    m.d.sync += [
                        osc[self.address].wfdr_buffer.eq(
                            osc[self.address].wfdr_buffer
                            | (self.data_in[3:0] & self.write_mask)
                        ),
                        osc[self.address].wfdr_mask.eq(
                            osc[self.address].wfdr_mask | self.write_mask
                        )
                    ]

        return m

class LFORegisterFile:
    def __init__(self):
        self.phase_increment = Signal(16)
        self.phase_accumulator = Signal(16)
        self.waveform = Signal(2)
        self.direction = Signal(1)
        self.sine_delay = Signal(16)
        self.cosine_delay = Signal(16)
        self.wfdr_buffer = Signal(4)
        self.wfdr_mask = Signal(4)

    def is_ramp(self):
        return (self.waveform == 0)

    def is_square(self):
        return (self.waveform == 1)

    def is_triangle(self):
        return (self.waveform == 2)

    def is_sine(self):
        return (self.waveform == 3)

    def is_resetting(self):
        return (self.wfdr_buffer[0] & self.wfdr_mask[0])
