"""MiniDSP SHD Platform.

Volumio rest API: https://volumio.github.io/docs/API/REST_API.html

MiniDSP SHD devices are audio DAC/processors that have an embedded Volumio
server on a nanopi board. This can control some aspects of the MiniDSP
device via the normal Volumio API.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import json
from typing import Any

from pyvolumio import CannotConnectError

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ID, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import Throttle

from .browse_media import browse_node, browse_top_level
from .const import DATA_INFO, DATA_VOLUMIO, DOMAIN, MINIDSP_VARIANT

# three possible sets of features: MiniDSP as a DAC, MiniDSP as a Volumio server, normal Volumio

FEATURES_AS_DAC = (
    MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
)

FEATURES_AS_SERVER = (
    MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.REPEAT_SET
    | MediaPlayerEntityFeature.SHUFFLE_SET
    | MediaPlayerEntityFeature.CLEAR_PLAYLIST
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
)

FEATURES_AS_VOLUMIO = (
    MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.REPEAT_SET
    | MediaPlayerEntityFeature.SHUFFLE_SET
    | MediaPlayerEntityFeature.CLEAR_PLAYLIST
    | MediaPlayerEntityFeature.BROWSE_MEDIA
)

MINIDSP_LAN = "LAN"

PLAYLIST_UPDATE_INTERVAL = timedelta(seconds=15)
RETRY_LIMIT = 3
VOLUMIO_REQUEST_TIMEOUT = 5

PRESET_MAP = {
    "Preset 1": "presets/id/1",
    "Preset 2": "presets/id/2",
    "Preset 3": "presets/id/3",
    "Preset 4": "presets/id/4",
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Volumio media player platform."""

    data = hass.data[DOMAIN][config_entry.entry_id]
    volumio = data[DATA_VOLUMIO]
    info = data[DATA_INFO]
    uid = config_entry.data[CONF_ID]
    name = config_entry.data[CONF_NAME]

    entity = Volumio(volumio, uid, name, info)
    async_add_entities([entity])


class Volumio(MediaPlayerEntity):
    """Volumio Player Object."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_media_content_type = MediaType.MUSIC
    _attr_supported_features = FEATURES_AS_VOLUMIO
    _attr_source_list = []
    _attr_sound_mode_list = []
    _attr_volume_step = 0.03

    def __init__(self, volumio, uid, name, info) -> None:
        """Initialize the media player."""
        self._volumio = volumio
        unique_id = uid
        self._state = {}
        self._systeminfo = None
        self._minidsp = False
        self._source_map = {}
        self._is_available = False
        self._retry_count = 0
        self.thumbnail_cache = {}
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            manufacturer="Volumio",
            model=info["hardware"],
            name=name,
            sw_version=info["systemversion"],
        )

    async def _async_build_minidsp_lists(self):
        """For MiniDSP SHD, build list of actual hardware inputs and presets."""
        nav = await self._volumio.browse("inputs")
        for item in nav["lists"][0]["items"]:
            self._source_map[item["title"]] = item["uri"]
        self._source_map[MINIDSP_LAN] = '{"uri":"/mnt/NONEXISTENT.flac"}'
        self._attr_source_list = sorted(self._source_map)
        self._attr_sound_mode_list = sorted(PRESET_MAP)

    async def async_update(self) -> None:
        """Update state."""

        try:
            if self._systeminfo is None:
                async with asyncio.timeout(VOLUMIO_REQUEST_TIMEOUT):
                    self._systeminfo = await self._volumio.get_system_info()
                if MINIDSP_VARIANT in self._systeminfo.get("variant", None):
                    self._minidsp = True
                    await self._async_build_minidsp_lists()

            async with asyncio.timeout(VOLUMIO_REQUEST_TIMEOUT):
                self._state = await self._volumio.get_state()

            if self._minidsp:
                if self._state.get("title") in self._attr_source_list:
                    self._attr_source = self._state.get("title")
                    self._attr_supported_features = FEATURES_AS_DAC
                else:
                    self._attr_source = MINIDSP_LAN
                    self._attr_supported_features = FEATURES_AS_SERVER
            else:
                async with asyncio.timeout(VOLUMIO_REQUEST_TIMEOUT):
                    await self._async_update_playlists()
            self._retry_count = 0
            self._is_available = True

        except (CannotConnectError, TimeoutError):
            # mark as unavailable after several consecutive failures
            self._retry_count += 1
            if self._retry_count > RETRY_LIMIT:
                self._is_available = False
                self._retry_count = 0

    @property
    def available(self) -> bool:
        """Is the media player available."""
        return self._is_available

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        status = self._state.get("status", None)
        if self._minidsp and self._state.get("trackType") == "input":
            return MediaPlayerState.IDLE
        if status == "pause":
            return MediaPlayerState.PAUSED
        if status == "play":
            return MediaPlayerState.PLAYING

        return MediaPlayerState.IDLE

    @property
    def media_title(self):
        """Title of current playing media."""
        mytitle = self._state.get("title", None)
        if self._minidsp and mytitle == "":
            return MINIDSP_LAN
        return mytitle

    @property
    def media_artist(self):
        """Artist of current playing media (Music track only)."""
        return self._state.get("artist", None)

    @property
    def media_album_name(self):
        """Artist of current playing media (Music track only)."""
        return self._state.get("album", None)

    @property
    def media_image_url(self):
        """Image url of current playing media."""
        url = self._state.get("albumart", None)
        return self._volumio.canonic_url(url)

    @property
    def media_seek_position(self):
        """Time in seconds of current seek position."""
        return self._state.get("seek", None)

    @property
    def media_duration(self):
        """Time in seconds of current song duration."""
        return self._state.get("duration", None)

    @property
    def sound_mode(self) -> str | None:
        """The current mode cannot be read via the API, so just return None."""
        return None

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        volume = self._state.get("volume", None)
        if volume is not None and volume != "":
            volume = int(volume) / 100
        return volume

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._state.get("mute", None)

    @property
    def shuffle(self):
        """Boolean if shuffle is enabled."""
        return self._state.get("random", False)

    @property
    def repeat(self) -> RepeatMode:
        """Return current repeat mode."""
        if self._state.get("repeat", None):
            return RepeatMode.ALL
        return RepeatMode.OFF

    async def async_media_next_track(self) -> None:
        """Send media_next command to media player."""
        await self._volumio.next()

    async def async_media_previous_track(self) -> None:
        """Send media_previous command to media player."""
        await self._volumio.previous()

    async def async_media_play(self) -> None:
        """Send media_play command to media player."""
        await self._volumio.play()

    async def async_media_pause(self) -> None:
        """Send media_pause command to media player."""
        if self._state.get("trackType") == "webradio":
            await self._volumio.stop()
        else:
            await self._volumio.pause()

    async def async_media_stop(self) -> None:
        """Send media_stop command to media player."""
        await self._volumio.stop()

    async def async_set_volume_level(self, volume: float) -> None:
        """Send volume_up command to media player."""
        await self._volumio.set_volume_level(int(volume * 100))

    async def async_mute_volume(self, mute: bool) -> None:
        """Send mute command to media player."""
        if mute:
            await self._volumio.mute()
        else:
            await self._volumio.unmute()

    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Enable/disable shuffle mode."""
        await self._volumio.set_shuffle(shuffle)

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        """Set repeat mode."""
        if repeat == RepeatMode.OFF:
            await self._volumio.repeatAll("false")
        else:
            await self._volumio.repeatAll("true")

    async def async_select_source(self, source: str) -> None:
        """Choose an available playlist and play it."""
        if not self._minidsp:
            await self._volumio.play_playlist(source)
        elif source == MINIDSP_LAN:
            await self._volumio.replace_and_play(json.loads(self._source_map[source]))
        else:
            await self._volumio.browse(self._source_map[source])
        self._attr_source = source

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Select one of the presets."""
        await self._volumio.browse(PRESET_MAP[sound_mode])

    async def async_clear_playlist(self) -> None:
        """Clear players playlist."""
        await self._volumio.clear_playlist()
        self._attr_source = None

    @Throttle(PLAYLIST_UPDATE_INTERVAL)
    async def _async_update_playlists(self, **kwargs):
        """Update available Volumio playlists."""
        if not self._minidsp:
            self._attr_source_list = await self._volumio.get_playlists()

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Send the play_media command to the media player."""
        await self._volumio.replace_and_play(json.loads(media_id))

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Implement the websocket media browsing helper."""
        self.thumbnail_cache = {}
        if media_content_type in (None, "library"):
            return await browse_top_level(self._volumio)

        return await browse_node(
            self, self._volumio, media_content_type, media_content_id
        )

    async def async_get_browse_image(
        self,
        media_content_type: MediaType | str,
        media_content_id: str,
        media_image_id: str | None = None,
    ) -> tuple[bytes | None, str | None]:
        """Get album art from Volumio."""
        cached_url = self.thumbnail_cache.get(media_content_id)
        image_url = self._volumio.canonic_url(cached_url)
        return await self._async_fetch_image(image_url)
