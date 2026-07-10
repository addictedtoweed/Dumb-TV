# Drop your video streams here

Put up to 16 clips named **`vid_0`** through **`vid_15`** in this folder (any
common container works — `.mp4 .mkv .mov .avi .webm .m4v .y4m`). They're the 16
inputs of the TV's mux; the sim decodes and loops them with OpenCV, **no
re-encoding needed**.

    vid_0.mp4
    vid_1.mkv
    vid_2.mov
    ...
    vid_15.mp4

Any input without a file falls back to a distinct animated test pattern, so you
can start with zero files and add clips as you like.

Real-video decoding needs OpenCV (`pip install opencv-python`, or use the
launcher which installs it for you). Without it, all 16 inputs are synthetic.
