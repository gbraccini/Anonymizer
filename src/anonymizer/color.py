"""!
@file color.py
@brief Valida la semantica colore delle sorgenti e normalizza i pixel decodificati in sRGB.

Interpreta gamma, flag sRGB, cromaticità e profili ICC dei metadati immagine e rifiuta
quelli non validi o non supportati, così che i colori clinici non vengano alterati
silenziosamente durante il rendering e l'esportazione.
"""

import math
from io import BytesIO

from anonymizer.visual_model import DocumentError

## Cromaticità di riferimento sRGB (punto di bianco D65 e primari R, G, B come coppie x, y).
_SRGB_CHROMATICITY = (0.3127, 0.3290, 0.64, 0.33, 0.30, 0.60, 0.15, 0.06)


def color_transform(image):
    """!
    @brief Costruisce la trasformazione colore verso sRGB senza caricare il raster sorgente.

    Usa solo i metadati dell'immagine, così può essere chiamata durante l'ispezione dei
    budget prima della decodifica dei pixel.
    @param image Immagine PIL aperta di cui leggere i metadati colore.
    @return None se non serve alcuna conversione, una tupla di 256 valori (tabella di
        correzione gamma) oppure una trasformazione ImageCms da profilo ICC a sRGB.
    @throws DocumentError Se gamma, flag sRGB, cromaticità o profilo ICC sono non validi,
        se il profilo ICC non è utilizzabile o se i primari non sRGB non hanno un profilo ICC.
    """
    info = image.info
    gamma = info.get("gamma")
    if gamma is not None and (
        not isinstance(gamma, (int, float)) or not math.isfinite(gamma) or not 0 < gamma <= 10
    ):
        raise DocumentError("invalid_color_profile")
    srgb = info.get("srgb")
    if srgb is not None and (type(srgb) is not int or srgb not in range(4)):
        raise DocumentError("invalid_color_profile")
    chroma = info.get("chromaticity")
    if chroma is not None:
        if (
            not isinstance(chroma, tuple)
            or len(chroma) != 8
            or not all(
                isinstance(c, (int, float)) and math.isfinite(c) and 0 < c < 1 for c in chroma
            )
        ):
            raise DocumentError("invalid_color_profile")
    if "icc_profile" in info:
        from PIL import ImageCms

        profile = info["icc_profile"]
        if not isinstance(profile, bytes) or not 128 <= len(profile) <= 4 * 1024 * 1024:
            raise DocumentError("invalid_color_profile")
        if profile[36:40] != b"acsp" or int.from_bytes(profile[:4], "big") != len(profile):
            raise DocumentError("invalid_color_profile")
        try:
            source = ImageCms.ImageCmsProfile(BytesIO(profile))
            target = ImageCms.createProfile("sRGB")
            return ImageCms.buildTransformFromOpenProfiles(source, target, image.mode, "RGB")
        except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
            raise DocumentError("invalid_or_unsupported_color_profile") from None
    if chroma is not None and any(
        abs(a - b) > 0.0001 for a, b in zip(chroma, _SRGB_CHROMATICITY, strict=True)
    ):
        # Non-sRGB primaries need an ICC profile; silently stripping them changes clinical colors.
        raise DocumentError("unsupported_color_profile_primaries")
    if srgb is not None or gamma is None:
        return None
    return tuple(
        round(
            255 * (12.92 * linear if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055)
        )
        for i in range(256)
        for linear in [(i / 255) ** (1 / gamma)]
    )


def normalized_color_mode(image):
    """!
    @brief Calcola il modo colore che l'immagine avrà dopo la normalizzazione.
    @param image Immagine PIL aperta.
    @return "RGB" se verrà applicato un profilo ICC, altrimenti il modo originale.
    @throws DocumentError Se i metadati colore non sono validi o supportati.
    """
    transform = color_transform(image)
    return "RGB" if transform is not None and not isinstance(transform, tuple) else image.mode


def normalize_color(image):
    """!
    @brief Restituisce una copia dell'immagine convertita in sRGB e priva di metadati.

    Svuotare info evita che profili, gamma o altri metadati della sorgente finiscano
    nell'output.
    @param image Immagine PIL decodificata.
    @return Nuova immagine normalizzata in sRGB con info vuoto.
    @throws DocumentError Se i metadati colore non sono validi o la trasformazione ICC fallisce.
    """
    transform = color_transform(image)
    if transform is None:
        output = image.copy()
    elif isinstance(transform, tuple):
        output = image.point(list(transform) * (3 if image.mode == "RGB" else 1))
    else:
        from PIL import ImageCms

        try:
            output = ImageCms.applyTransform(image, transform)
        except (ImageCms.PyCMSError, OSError, ValueError):
            raise DocumentError("invalid_or_unsupported_color_profile") from None
    output.info.clear()
    return output
