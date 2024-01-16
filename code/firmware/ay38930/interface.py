# Interface to the AY-3-8930 and YM2149F
#
# 

from machine import Pin, freq
import rp2

class RegisterInterface:
    __init__(self):
        pass

class PIOInterface:
    __init__(self, da_base: Pin, bc1: Pin, bdir: Pin, clock: Pin, reset: Pin):
        assert freq() % (2*10**6) == 0, "machine.freq must be divisible by 2MHz"

        self.pio_req = freq() / 2000000

        self.da_pins = da_pins
        self.bc1_pin = bc1
        self.bdir_pin = bdir
        self.clock_pin = clock
        self.reset_pin = reset
        self._program_pio()

    # This program uses 3 bits for side set and has a delay of 0-3
    # 10 clock cycles per iteration, so the program must run at 20MHz
    # to provide the 2MHz clock the AY-3-8930 uses
    @rp2.asm_pio(set_init=rp2.PIO.OUT_LOW)
    def generate_interface(self):
        wrap_target()
        label("clock")

        # Set rising edge and wait 4 cycles (5 cycles high)
        set(pins,1) [3]
        nop()
        # Set falling edge and handle data for 5 cycles
        # Original chip is negative-edge latch based, so the driver
        # must zero the control pins here.  This also sets up 3/10 of
        # the chip's clock cycle before the rising edge, so a
        # synchronous clone should work.
        set(pins,0) .side(0b00)
        jmp(not_osre, "handle_output")
        # Add 4 cycles if not doing output
        nop() [3]
        wrap()

        # Set address
        # 3 clocks
        label("handle_output")
        jmp(x_dec, "set_data")
        out(pins,8) .side(0b11)
        set(x, 0b1)
        jmp("handle_clock")

        # Set data
        # 3 clocks
        label("set_data")
        out(pins,8) .side(0b10) [1]
        jmp("handle_clock")



