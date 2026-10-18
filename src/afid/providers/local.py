"""Local-import providers: firmware the user obtained themselves, processed locally.

Every brand provider below is local-import only: no official, documented, automatable
download API was verified for these brands (see docs/PROVIDERS.md). They differ in the
documented package formats and in file-name hints.
"""

from __future__ import annotations

import re

from afid.providers.base import Capabilities, FirmwareProvider

LOCAL = Capabilities(verify=True, local_import=True)


class LocalFirmwareProvider(FirmwareProvider):
    """Generic user-supplied firmware (archive, image or extracted directory)."""

    CAPABILITIES = LOCAL


class SamsungProvider(LocalFirmwareProvider):
    pass


class XiaomiFamilyProvider(LocalFirmwareProvider):
    """Xiaomi, POCO and Redmi share packaging (recovery ZIP with payload.bin, fastboot tgz);
    each brand keeps its own provider id and brand identity."""


class OnePlusProvider(LocalFirmwareProvider):
    pass


class TranssionProvider(LocalFirmwareProvider):
    """Infinix and TECNO."""


class NothingProvider(LocalFirmwareProvider):
    pass


class GooglePixelProvider(LocalFirmwareProvider):
    """Factory images and full OTAs from developers.google.com/android/{images,ota}.

    Those pages require accepting Google's terms in a browser before the image tables are
    shown, so AFID does not scrape or download them. Users download the package themselves,
    optionally pass the SHA-256 published on the page, and import it locally.
    """

    _FACTORY = re.compile(
        r"^(?P<codename>[a-z0-9]+)-(?P<build>[a-z0-9.]+)-factory-"
        r"(?P<hash>[0-9a-f]{8})\.zip$"
    )
    _OTA = re.compile(
        r"^(?P<codename>[a-z0-9]+)-ota-(?P<build>[a-z0-9.]+)-"
        r"(?P<hash>[0-9a-f]{8})\.zip$"
    )

    def filename_hints(self, name: str) -> dict[str, str]:
        for kind, rx in (("factory_image", self._FACTORY), ("full_ota", self._OTA)):
            m = rx.match(name.lower())
            if m:
                return {
                    "package_type": kind,
                    "codename": m["codename"],
                    "build_id": m["build"].upper(),
                    "basis": "file name pattern (hint)",
                }
        return {}
