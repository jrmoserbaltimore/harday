from amaranth import *
from amaranth.lib import coding
import numpy as np
from numpy import log2, sin, uint32, float64, power, pi
tau = 2*pi

# Bitcrusher for 24-bit audio, blanks out the bottom bits of the audio

class Bitcrusher(Elaboratable):
    """

    """
    def __init__(self):,
        self.clk = Signal(1)
        self.sample = Signal(24)
        self.crush = Signal(6)
        self.out = Signal(24)

    def elaborate(self, platform) -> Module:
        m = Module()

        m.d.comb += [
                self.out[23:self.crush].eq(self.sample[23:self.crush])
                ]
        with m.If(self.crush != 0):
            m.d.comb += self.out[crush-1:0].eq(0)
        return m

