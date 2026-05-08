#!/bin/sh
# Download the font family used by the character content renderer.
# Runs at image build time so fonts are baked into the container.
# All fonts are SIL OFL or Apache licensed, redistribution allowed.
#
# Two-tier strategy: first try github.com/google/fonts raw URLs (fast path for
# display fonts), then fall back to the Google Fonts CSS2 API for any that 404
# (some static cuts live at paths that change between repo reorgs).
set -e

FONTS_DIR="${FONTS_DIR:-/app/backend/assets/fonts}"
mkdir -p "$FONTS_DIR"

BASE="https://github.com/google/fonts/raw/main"

download() {
  # $1 = url path after $BASE/, $2 = output filename
  url="$BASE/$1"
  out="$FONTS_DIR/$2"
  if [ -f "$out" ] && [ -s "$out" ]; then
    echo "skip (exists): $2"
    return 0
  fi
  echo "fetch: $2"
  curl -fsSL --retry 3 --retry-delay 2 -o "$out" "$url" || {
    echo "WARN: github raw failed for $2, trying CSS API" >&2
    rm -f "$out"
  }
}

# Fallback: resolve a Google Fonts family/weight via the CSS2 API and fetch
# the .ttf it points to. Args: family (URL-encoded, + for spaces), weight, out.
download_css() {
  family="$1"; weight="$2"; out="$FONTS_DIR/$3"
  if [ -f "$out" ] && [ -s "$out" ]; then
    echo "skip (exists): $3"
    return 0
  fi
  css=$(curl -fsSL -A "Mozilla/5.0" "https://fonts.googleapis.com/css2?family=${family}:wght@${weight}&display=swap" 2>/dev/null || true)
  ttf=$(echo "$css" | grep -oE "https://[^)]+\.ttf" | head -1)
  if [ -n "$ttf" ]; then
    echo "fetch (css): $3"
    curl -fsSL --retry 2 -o "$out" "$ttf" || echo "WARN: css fetch failed for $3" >&2
  else
    echo "WARN: no TTF resolved for $family @ $weight" >&2
  fi
}

# Display/hook family
download "ofl/anton/Anton-Regular.ttf"                                  Anton-Regular.ttf
download "ofl/bebasneue/BebasNeue-Regular.ttf"                          BebasNeue-Regular.ttf
# Oswald — variable font with static cuts under /static/
download "ofl/oswald/static/Oswald-Bold.ttf"                            Oswald-Bold.ttf
download "ofl/oswald/static/Oswald-SemiBold.ttf"                        Oswald-SemiBold.ttf
download "ofl/archivoblack/ArchivoBlack-Regular.ttf"                    ArchivoBlack-Regular.ttf
download "ofl/staatliches/Staatliches-Regular.ttf"                      Staatliches-Regular.ttf
download "ofl/bangers/Bangers-Regular.ttf"                              Bangers-Regular.ttf

# Quote / editorial (static cuts for predictable pixel sizes)
download "ofl/playfairdisplay/static/PlayfairDisplay-Black.ttf"         PlayfairDisplay-Black.ttf
download "ofl/playfairdisplay/static/PlayfairDisplay-BlackItalic.ttf"  PlayfairDisplay-BlackItalic.ttf
download "ofl/abrilfatface/AbrilFatface-Regular.ttf"                    AbrilFatface-Regular.ttf
# Fraunces — static slant=0 black weight
download "ofl/fraunces/static/Fraunces_9pt-Black.ttf"                   Fraunces-Black.ttf

# Handwritten / marker
download "apache/permanentmarker/PermanentMarker-Regular.ttf"           PermanentMarker-Regular.ttf
# Shadows Into Light — repo stores as ShadowsIntoLight-Regular under /ofl/
download "ofl/shadowsintolight/ShadowsIntoLight-Regular.ttf"            ShadowsIntoLight-Regular.ttf
download "ofl/caveatbrush/CaveatBrush-Regular.ttf"                      CaveatBrush-Regular.ttf
download "ofl/caveat/static/Caveat-Bold.ttf"                            Caveat-Bold.ttf
download "apache/homemadeapple/HomemadeApple-Regular.ttf"               HomemadeApple-Regular.ttf

# Mono / tech / terminal
download "ofl/rubikmonoone/RubikMonoOne-Regular.ttf"                    RubikMonoOne-Regular.ttf
download "ofl/vt323/VT323-Regular.ttf"                                  VT323-Regular.ttf
# ChakraPetch — static cuts are at top of ofl/chakrapetch
download "ofl/chakrapetch/ChakraPetch-Bold.ttf"                         ChakraPetch-Bold.ttf

# Themed / specialty
download "ofl/orbitron/static/Orbitron-Black.ttf"                       Orbitron-Black.ttf
download "ofl/creepster/Creepster-Regular.ttf"                          Creepster-Regular.ttf
download "ofl/monoton/Monoton-Regular.ttf"                              Monoton-Regular.ttf
download "ofl/unifrakturmaguntia/UnifrakturMaguntia-Book.ttf"           UnifrakturMaguntia.ttf
download "ofl/rubikglitch/RubikGlitch-Regular.ttf"                      RubikGlitch-Regular.ttf
download "ofl/pirataone/PirataOne-Regular.ttf"                          PirataOne-Regular.ttf
download "ofl/cinzel/static/Cinzel-Black.ttf"                           Cinzel-Black.ttf

# Body / fallbacks. Inter uses variable+static layout; Roboto is apache.
download "ofl/inter/static/Inter-Black.ttf"                             Inter-Black.ttf
download "ofl/inter/static/Inter-Bold.ttf"                              Inter-Bold.ttf
# Roboto static cuts live at apache/roboto/static
download "apache/roboto/static/Roboto-Black.ttf"                        Roboto-Black.ttf
download "apache/roboto/static/Roboto-Bold.ttf"                         Roboto-Bold.ttf

# CSS API fallbacks for fonts whose github raw paths move between releases.
download_css "Oswald"             700 Oswald-700.ttf
download_css "Playfair+Display"   900 PlayfairDisplay-900.ttf
download_css "Roboto"             900 Roboto-900.ttf
download_css "Inter"              900 Inter-900.ttf
download_css "Caveat"             700 Caveat-700.ttf
download_css "Orbitron"           900 Orbitron-900.ttf
download_css "Cinzel"             900 Cinzel-900.ttf
download_css "Shadows+Into+Light" 400 ShadowsIntoLight-400.ttf
download_css "Fraunces"           900 Fraunces-900.ttf
download_css "Archivo+Black"      400 ArchivoBlack-400.ttf
download_css "Bebas+Neue"         400 BebasNeue-400.ttf

echo "done: $(ls -1 "$FONTS_DIR" | wc -l) fonts in $FONTS_DIR"
