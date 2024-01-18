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

    @rp2.asm_pio()
    def run_clock(self):
        wrap_target()
        # Rising edge
        irq(0)
        set(pins,1)

        irq(1)
        set(pins,0)

    # Sets IRQ 2 and waits for it to be 0, then sets pins to out.
    # Sets IRQ 3 and waits for it to be 0, then sets pins to in.
    # Clearing 2 when the pins are already out, or 3 when pins are in,
    # doesn't affect execution flow.
    @rp2.asm_pio(set_init=rp2.PIO.OUT_LOW)
    def da_direction(self):
        wrap_target()
        mov(osr,invert(null))
        irq(block, 2)
        out(pindirs,8)
        mov(osr,null)
        irq(block, 3)
        out(pindirs,8)
        wrap()

    # Following IRQ 0:
    #  - 5 instructions for set address to reach falling edge
    #  - Same for writing data
    #  - 3 and then wait for falling edge to read data
    # Following IRQ 1:
    #  - 0 instruction and then wait for rising edge for DA
    #  - 2 instruction and then wait for rising edge for read
    @rp2.asm_pio()
    def latched_io:
        label("finish write")
        # wait for falling edge, then clear the control pins
        wait(1, irq, 1) .side(0b00)

        label("reenter")
        # Loop until a rising edge occurs with something in the OSR
        .wrap_target()
        wait(1, irq, 0)
        jmp(not_osre, "handle")
        wrap()

        # Handle i/o, jump to location given on input.
        label("handle")
        out(pc, 5)

        label("set address")
        # Ensure DA are out pins
        irq(clear, 2)
        out(pins, 8) .side(0b11)
        jmp("finish write")

        label("set data")
        irq(clear, 2)
        out(pins, 8) .side(0b10)
        jmp("finish write")

        label("get data")
        # Ensure DA are in pins
        irq(clear, 3) .side(0b01)
        wait(1, irq, 1)
        in(pins, 8)
        jmp("reenter") .side(0b00)

    def _write_address(self, address:int):
        # FIXME:  Send the address and the 5-bit jump target
        self.pio_sm.put()

    def _write_register(self, address: int, value: int, page: int = 0):
        self.pio_sm.put((address & 0xff) | ((value & 0xff) << 8))

