# Interface to the AY-3-8930 and YM2149F
#
# 

from machine import Pin, freq
import rp2

class RegisterInterface:
    __init__(self):
        pass

class PIOInterface:
    __init__(self, da_base: Pin, bc1: Pin, clock: Pin, reset: Pin):
        assert freq() % (2*10**6) == 0, "machine.freq must be divisible by 2MHz"

        self.pio_req = freq() / 2000000

        self.da_pins = da_pins
        self.bc1_pin = bc1
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

    # OSR format:
    #   |31-21        |20-13    |12-8  |7-0     |
    #   |0000 0000 000|data     |fnc   |pindirs |

    # The latched I/O interface is for the 5V AY-3-89xx and YM2149 and
    # is divorced from the clock. It has 300ns setup and 65ns hold.
    # Each clock tick must be more than 75ns (13MHz) to meet the below
    # timing.
    #
    # OSR       *
    # bc1/bdir  ___----_
    # da           *
    # pindir     *
    # delay         +++

    @rp2.asm_pio()
    def latched_io(self):
        label("reenter")
        # Close all latches
        nop() .side(0b00)
        .wrap_target()
        jmp(not_osre, "handle")
        wrap()

        # Handle i/o, jump to location given on input.
        label("handle")
        out(pindirs, 8)
        out(pc, 5)

        label("set address")
        out(pins, 8) .side(0b11) [3]
        jmp("reenter")

        label("set data")
        out(pins, 8) .side(0b10) [3]
        jmp("reenter")

        # Data is read on the falling edge in the original AY-3
        label("get data")
        # Reading, so discard the last 8 bits of OSR
        # Data READ setup time is max 200ns, hold is 100ns, so 225ns
        # and then in()
        out(null, 8) .side(0b01) [2]
        in(pins, 8)
        jmp("reenter") .side(0b00)

    # The sync_io() interface is designed for 96kHz sample rate chips
    # running at 9.216MHz or 24.576MHz.
    @rp2.asm_pio()
    def sync_io(self):
        label("reenter")
        # Loop until a rising edge occurs with something in the OSR
        .wrap_target()
        wait(1, irq, 0)
        jmp(not_osre, "handle")
        wrap()

        # Handle i/o, jump to location given on input.
        label("handle")
        out(pindirs, 8)
        out(pc, 5)
        # FIXME:  Implement this

    def _write_address(self, address:int):
        # FIXME:  Send the address and the 5-bit jump target
        self.pio_sm.put()

    def _write_register(self, address: int, value: int, page: int = 0):
        self.pio_sm.put((address & 0xff) | ((value & 0xff) << 8))

