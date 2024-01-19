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
    # is divorced from the clock.  Timings in ns are:
    # 
    #                8910  YM2149  8930
    # Address setup   400     300   300
    # Address hold    100      80    65
    # Write setup      50       0   300      
    # Write pulse    1800     300     *
    # Write hold      100      80    65
    # Read access     350     400   200
    #
    # The 8930 has no real "write setup"; rather, it must have the data
    # on the bus for 300ns before lowering the control bus, and 65ns
    # after.  The others need the data on the bus before setting data
    # write on the control bus.  Address "setup" on all chips works the
    # the same as the 8930 data "setup."
    #
    # Each clock tick must be more than 100ns (10MHz) to meet the above
    # timing.  Writes are stretched out a lot because of the long write
    # pulse of the 8910.
    #
    # OSR       *
    # bc1/bdir  ___----_
    # da           *
    # pindir     *
    # delay         +++

    @rp2.asm_pio()
    def latched_io(self):
        label("reenter")
        # Close all latches while spinning
        .wrap_target()
        jmp(not_osre, "handle") .side(0b00)
        wrap()

        # Handle i/o, jump to location given on input.
        label("handle")
        out(pindirs, 8)
        out(pc, 5)

        label("set address")
        out(pins, 8) .side(0b11) [3]
        jmp("reenter")

        # Long write pulse for the original 8910
        label("set data")
        out(pins, 8)
        set(x, 3) .side(0b10) [3]
        label("write pulse")
        jmp(dec_x, "write pulse") [3]
        jmp("reenter")

        # Data is read on the falling edge in the original AY-3
        label("get data")
        # Reading, so discard the last 8 bits of OSR
        # Data READ access time is max 350ns, so delay to 400ns
        out(null, 8) .side(0b01) [3]
        in(pins, 8)
        # Reset the control bus ASAP because it may take 400ns to
        # settle after reading
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

