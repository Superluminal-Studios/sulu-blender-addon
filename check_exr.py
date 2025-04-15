import OpenEXR
import Imath

file = OpenEXR.InputFile("/tmp/pee/0001.exr")
header = file.header()
channels = list(header['channels'].keys())

print("Channels:", channels)
