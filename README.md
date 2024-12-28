# minidspshd
Home Assistant Custom Component for MiniDSP SHD

This Home Assistant integration provides a simple Media Player interface
to a MiniDSP SHD streamer / DAC.  It is based on the existing HA Volumio
integration, slightly modified to allow proper control of the SHD's hardware inputs 
and DSP presets. It also has improved handling for device unreachability, as 
an SHD is more likely to be turned off and on than a dedicated Volumio server.

The integration supports Zeroconf, so will auto-discover an SHD that's connected to
your network. The built in Volumio integration will also discover the SHD, so you should
press the Ignore button for that instance. You could of course enable both, but that 
would probably be more confusing than useful.

Note that there is no way to read the currently selected DSP preset from the API, so
this setting is write-only.

The integration currently needs to be manually installed into the custom_components directory of your 
Home Assistant installation.  I will be attempting to get it installable via HACS in due course. In 
the meantime, you will need to have SSH access to your Home Assistant system. Use wget or curl to
download the latest release from github, and unpack the tar or zip file. The actual files you need
for the integration are in the custom_components/minidspshd directory in the archive, and this is also 
where they need to end up on your system when you've unpacked the release. For example:

```
~ # cd /root/config/custom_components
custom_components # ls -l minidspshd
total 48
-rw-r--r--    1 root     root          1347 Dec 19 15:28 __init__.py
-rw-r--r--    1 root     root          5119 Dec 19 15:28 browse_media.py
-rw-r--r--    1 root     root          4092 Dec 19 15:28 config_flow.py
-rw-r--r--    1 root     root           315 Dec 19 15:28 const.py
-rw-r--r--    1 root     root           341 Dec 19 15:28 manifest.json
-rw-r--r--    1 root     root         11052 Dec 19 15:28 media_player.py
-rw-r--r--    1 root     root           706 Dec 19 15:28 strings.json
drwxr-xr-x    2 root     root          4096 Dec 19 15:28 translations
```

Then restart Home Assistant and go to the Devices page within Settings to add the new device.
