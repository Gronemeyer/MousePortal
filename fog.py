#!/usr/bin/env python

# Author: Shao Zhang and Phil Saltzman
# Last Updated: 2015-03-13
#
# This tutorial will cover fog and how it can be used to make a finite length
# tunnel seem endless by hiding its endpoint in darkness. Fog in panda works by
# coloring objects based on their distance from the camera. Fog is not a 3D
# volume object like real world fog.
# With the right settings, Fog in panda can mimic the appearence of real world # fog.
#
# The tunnel and texture was originally created by Vamsi Bandaru and Victoria
# Webb for the Entertainment Technology Center class Building Virtual Worlds

from direct.showbase.ShowBase import ShowBase
from panda3d.core import Fog
from panda3d.core import TextNode
from direct.gui.OnscreenText import OnscreenText
from direct.showbase.DirectObject import DirectObject
from direct.interval.MetaInterval import Sequence
from direct.interval.LerpInterval import LerpFunc
from direct.interval.FunctionInterval import Func
import sys

# Global variables for the tunnel dimensions and speed of travel
TUNNEL_SEGMENT_LENGTH = 50
TUNNEL_TIME = 2  # Amount of time for one segment to travel the
# distance of TUNNEL_SEGMENT_LENGTH


class FogDemo(ShowBase):

    # Macro-like function used to reduce the amount to code needed to create the
    # on screen instructions
    def genLabelText(self, i, text):
        return OnscreenText(text=text, parent=base.a2dTopLeft, scale=.05,
                            pos=(0.06, -.065 * i), fg=(1, 1, 1, 1),
                            align=TextNode.ALeft)

    def __init__(self):
        # Initialize the ShowBase class from which we inherit, which will
        # create a window and set up everything we need for rendering into it.
        ShowBase.__init__(self)

        # Standard initialization stuff
        # Standard title that's on screen in every tutorial
        self.title = OnscreenText(text="Panda3D: Tutorial - Fog", style=1,
            fg=(1, 1, 1, 1), shadow=(0, 0, 0, .5), parent=base.a2dBottomRight,
            align=TextNode.ARight, pos=(-0.1, 0.1), scale=.08)

        # Code to generate the on screen instructions
        self.escapeEventText = self.genLabelText(1, "ESC: Quit")
        self.pkeyEventText = self.genLabelText(2, "[P]: Pause")
        self.tkeyEventText = self.genLabelText(3, "[T]: Toggle Fog")
        self.dkeyEventText = self.genLabelText(4, "[D]: Make fog color black")
        self.sdkeyEventText = self.genLabelText(5, "[SHIFT+D]: Make background color black")
        self.rkeyEventText = self.genLabelText(6, "[R]: Make fog color red")
        self.srkeyEventText = self.genLabelText(7, "[SHIFT+R]: Make background color red")
        self.bkeyEventText = self.genLabelText(8, "[B]: Make fog color blue")
        self.sbkeyEventText = self.genLabelText(9, "[SHIFT+B]: Make background color blue")
        self.gkeyEventText = self.genLabelText(10, "[G]: Make fog color green")
        self.sgkeyEventText = self.genLabelText(11, "[SHIFT+G]: Make background color green")
        self.lkeyEventText = self.genLabelText(12, "[L]: Make fog color light grey")
        self.slkeyEventText = self.genLabelText(13, "[SHIFT+L]: Make background color light grey")
        self.pluskeyEventText = self.genLabelText(14, "[+]: Increase fog density")
        self.minuskeyEventText = self.genLabelText(15, "[-]: Decrease fog density")

        # Create an instance of fog called 'distanceFog'.
        #'distanceFog' is just a name for our fog, not a specific type of fog.
        self.fog = Fog('distanceFog')
        # Set the initial color of our fog to black.
        self.fog.setColor(0, 0, 0)
        # Set the density/falloff of the fog.  The range is 0-1.
        # The higher the numer, the "bigger" the fog effect.
        self.fog.setExpDensity(.08)
        # We will set fog on render which means that everything in our scene will
        # be affected by fog. Alternatively, you could only set fog on a specific
        # object/node and only it and the nodes below it would be affected by
        # the fog.
        render.setFog(self.fog)

        # Define the keyboard input
        # Escape closes the demo
        self.accept('escape', sys.exit)
        # Handle pausing the tunnel
        self.accept('p', self.handlePause)
        # Handle turning the fog on and off
        self.accept('t', toggleFog, [render, self.fog])
        # Sets keys to set the fog to various colors
        self.accept('r', self.fog.setColor, [1, 0, 0])
        self.accept('g', self.fog.setColor, [0, 1, 0])
        self.accept('b', self.fog.setColor, [0, 0, 1])
        self.accept('l', self.fog.setColor, [.7, .7, .7])
        self.accept('d', self.fog.setColor, [0, 0, 0])
        # Sets keys to change the background colors
        self.accept('shift-r', base.setBackgroundColor, [1, 0, 0])
        self.accept('shift-g', base.setBackgroundColor, [0, 1, 0])
        self.accept('shift-b', base.setBackgroundColor, [0, 0, 1])
        self.accept('shift-l', base.setBackgroundColor, [.7, .7, .7])
        self.accept('shift-d', base.setBackgroundColor, [0, 0, 0])
        # Increases the fog density when "+" key is pressed
        self.accept('+', self.addFogDensity, [.01])
        # This is to handle the other "+" key (it's over = on the keyboard)
        self.accept('=', self.addFogDensity, [.01])
        self.accept('shift-=', self.addFogDensity, [.01])
        # Decreases the fog density when the "-" key is pressed
        self.accept('-', self.addFogDensity, [-.01])

    # This function will change the fog density by the amount passed into it
    # This function is needed so that it can look up the current value and
    # change it when the key is pressed. If you wanted to bind a key to set it
    # at a given value you could call self.fog.setExpDensity directly
    def addFogDensity(self, change):
        # The min() statement makes sure the density is never over 1
        # The max() statement makes sure the density is never below 0
        self.fog.setExpDensity(
            min(1, max(0, self.fog.getExpDensity() + change)))

    # This function calls toggle interval to pause or unpause the tunnel.
    # Like addFogDensity, toggleInterval could not be passed directly in the
    # accept command since the value of self.tunnelMove changes whenever
    #self.contTunnel is called
    def handlePause(self):
        toggleInterval(self.tunnelMove)
# End Class World


# This function will toggle any interval passed to it between playing and
# paused
def toggleInterval(interval):
    if interval.isPlaying():
        interval.pause()
    else:
        interval.resume()


# This function will toggle fog on a node
def toggleFog(node, fog):
    # If the fog attached to the node is equal to the one we passed in, then
    # fog is on and we should clear it
    if node.getFog() == fog:
        node.clearFog()
    # Otherwise fog is not set so we should set it
    else:
        node.setFog(fog)

