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
        self.phase_increment = []
        self.phase_accumulator = []
        self.waveform = []
        self.direction = []
        self.sine_delay = []
        self.cosine_delay = []
        self.wfdr_buffer = []
        self.wfdr_mask = []
        for x in range(0,int):
            self.phase_increment.append(Signal(16))
            self.phase_accumulator.append(Signal(16))
            self.waveform.append(Signal(2))
            self.direction.append(Signal(1))
            self.sine_delay.append(Signal(16))
            self.cosine_delay.append(Signal(16))
            self.wfdr_buffer.append(Signal(4))
            self.wfdr_mask.append(Signal(4))
        # Updating state tracks which oscillator is being updated 
        self.updating = Signal(count)

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
        
        # Data for sine and cosine update, the index of the register to
        # update, and whether to update.  For pipelining updates.
        sine_update = [Signal(16) for x in range(0,self.multiplier_delay)]
        cosine_update = [Signal(16) for x in range(0,self.multiplier_delay)]
        sine_update_index = [Signal(ceil(log2(self.count))) for x in range (0,self.multiplier_delay)]
        sine_update_enable = [Signal(1) for x in range (0,self.multiplier_delay)]

        with m.If(self.update):
            m.d.sync += [
                    self.updating.eq(1)
                ]
        with m.If(any(self.updating)):
            # Get the index of the oscillator to update
            x = Signal(ceil(log2(self.count)))
            m.d.comb += x.eq(PriorityEncoder(self.count, self.updating).o)
            # Increment the target oscillator
            m.d.sync += self.updating.eq(self.updating << 1)
            
            # Decode Waveform
            ramp = self._is_ramp(self.waveform[x])
            square = self._is_square(self.waveform[x])
            triangle = self._is_triangle(self.waveform[x])
            sine = self._is_sine(self.waveform[x])
            PA = Signal(17)
            OutputPhase = Signal(16)
            NewDirection = Signal(1)
            # Sum to PA in the combinational domain, with the extra bit
            # for overflow
            m.d.comb += [
                PA.eq(self.phase_accumulator[x] +
                    mux(triangle,
                        self.phase_increment[x] << 1,
                        self.phase_increment[x]
                    )
                ),
                # Flip on overflow if triangle
                NewDirection.eq(self.direction ^ (PA[16] & triangle))
            ]
            m.d.sync += [
                # Store new sum in phase accumulator
                self.phase_accumulator[x].eq(PA[0:15]),
                self.direction.eq(NewDirection)
            ]

            ##########################
            # Update sine oscillator #
            ##########################
            # The sine oscillator is much simpler:  it's a resonating
            # state variable filter.

            # Put the multiplication, index, and enable in the pipeline.
            # Does not cause an update if reset signal has been sent
            m.d.sync += [
                sine_update[0].eq(self.cosine_delay[x] * self.phase_increment[x]),
                cosine_update[0].eq(self.cosine_delay[x] * -self.phase_increment[x]),
                sine_update_index[0].eq(x),
                sine_update_enable[0].eq(~self._is_resetting(x))
            ]
            # Also execute the WFDR buffer.
            m.d.sync += [
                self.waveform[x].eq(
                    (self.waveform[x] & ~self.wfdr_mask[x][3:2])
                    | (self.wfdr_buffer[x][3:2] & self.wfdr_mask[x][3:2])
                ),
                # Clear the mask so these commands won't be executed
                # again next update
                self.wfdr_mask[x].eq(0)
            ]
            with m.If(self.wfdr_mask[x][1]):
                m.d.sync += self.direction[x].eq(self.wfdr_buffer[x][1])
            # Reset signal
            with m.If(self._is_resetting(x)):
                m.d.sync += self.phase_accumulator[x].eq(0)
                # Clear the sine wave.  Move tau/2 forward if
                # direction is 1 (i.e. reverse sine).
                #
                # If we're setting Direction, then use the
                # incoming value; else use the registered value
                m.d.sync += self.sine_delay[x].eq(0)
                with m.Switch(mux(self.wfdr_mask[x][1], self.wfdr_buffer[x][1],
                                  self.direction[x])):
                    with m.Case(0):
                        m.d.sync += self.cosine_delay[x].eq(1)
                    with m.Case(1):
                        m.d.sync += self.cosine_delay[x].eq(-1)
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
                sine_update_enable[0].eq(0)
            ]

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
                self.sine_delay[idx].eq(sine_update[i] + self.sine_delay[idx]),
                self.cosine_delay[idx].eq(cosine_update[i] + self.cosine_dealy[idx])
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
        with m.If(self._is_sine(self.waveform[self.address])):
            m.d.sync += self.data_out.eq(self.sine_delay[self.address])
        with m.Elif(self._is_square(self.waveform[self.address])):
            # Square, take the MSB, XOR with direction, and shift to
            # MSB.  Direction inverts duty cycle.
            m.d.sync += self.data_out.eq(
                        (self.phase_accumulator[self.address][15] ^ self.direction[self.address]) << 15
                    )
        with m.Else():
            # Ramps and triangles invert if Direction is 1; triangles
            # invert Direction when they overflow, ramps can slope up
            # or down
            m.d.sync += self.data_out.eq(
                            (self.phase_accumulator[self.address] ^ self.direction[self.address].replicate(16))
                            + self.direction[self.address]
                        )
        with m.If(self.write_enable):
            # Select either the PhaseIncrement register or the
            # Waveform, Direction, and Reset command
            with m.Switch(self.write_select):
                with m.Case(0):
                    m.d.sync += self.phase_increment[self.address].eq(self.data_in)
                # Buffer WFDR for application during update
                with m.Case(1):
                    m.d.sync += [
                        self.wfdr_buffer[self.address].eq(
                            self.wfdr_buffer[self.address]
                            | (self.data_in[3:0] & self.write_mask)
                        ),
                        self.wfdr_mask[self.address].eq(
                            self.wfdr_mask[self.address] | self.write_mask
                        )
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
    
    def _is_resetting(self, index: int):
        return (self.wfdr_buffer[index][0] & self.wfdr_mask[index][0])