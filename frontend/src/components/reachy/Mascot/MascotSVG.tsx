/**
 * MascotSVG — the actual face. Pure SVG, no 3D, no video. ~200 lines.
 *
 * Inspired by openhuman's YellowMascot. Reachy's mascot is a yellow disc
 * with two big round eyes, two cheek dots, two antennas (matching the
 * physical robot's expressive antennas), and a parametric mouth driven by
 * `{openness, width}` from the viseme stream.
 *
 * Face poses are CSS-only deltas on eye scale, brow tilt, and antenna
 * angle. Mouth path is computed each render from the current viseme. All
 * transitions use a 60 ms ease-out so the animation feels alive but never
 * jittery.
 */

import { useMemo } from 'react'

import { VISEMES, type VisemeShape } from './visemes'

import type { MascotFace } from './useMascot'

export interface MascotSVGProps {
  face: MascotFace
  viseme: VisemeShape
  /** Whether to animate the antennas (false in popout / mini contexts). */
  animateAntennas?: boolean
  /** Optional override for the body color. */
  color?: string
  className?: string
  size?: number | string
}

const FACE_COLOR_DEFAULT = '#fbbf24' // amber-400, matches existing UI accent
const SHADOW_COLOR = '#f59e0b'

/**
 * Build the mouth path. The viseme defines openness (0..1) and width (0..1).
 * We render the mouth as a smile (top arc + bottom arc) whose vertical
 * spread scales with openness and horizontal scale with width.
 */
function buildMouthPath(v: VisemeShape): string {
  const cx = 100
  const cy = 130
  // Half-width range: 18px (very pursed) → 38px (wide grin)
  const halfW = 18 + v.width * 20
  // Open height: 0 (closed) → 24
  const openH = v.openness * 24
  const topY = cy - 1
  const bottomY = cy + openH
  // Smooth lips with quadratic Bézier on each side.
  return [
    `M ${cx - halfW} ${cy}`,
    `Q ${cx} ${topY - 4} ${cx + halfW} ${cy}`,
    `Q ${cx} ${bottomY + 4} ${cx - halfW} ${cy}`,
    'Z',
  ].join(' ')
}

const FACE_POSE: Record<MascotFace, {
  eyeScaleY: number
  browAngle: number
  antennaAngle: number
  cheekOpacity: number
  bodyTilt: number
}> = {
  idle:        { eyeScaleY: 1.0, browAngle: 0,   antennaAngle:  -8, cheekOpacity: 0.45, bodyTilt: 0 },
  listening:   { eyeScaleY: 1.0, browAngle: 2,   antennaAngle:   6, cheekOpacity: 0.6,  bodyTilt: 1.5 },
  thinking:    { eyeScaleY: 0.6, browAngle: -6,  antennaAngle: -14, cheekOpacity: 0.3,  bodyTilt: -2 },
  speaking:    { eyeScaleY: 1.0, browAngle: 4,   antennaAngle:  10, cheekOpacity: 0.7,  bodyTilt: 0 },
  concerned:   { eyeScaleY: 0.85, browAngle: -10, antennaAngle: -20, cheekOpacity: 0.25, bodyTilt: -3 },
}

export function MascotSVG({
  face,
  viseme,
  animateAntennas = true,
  color = FACE_COLOR_DEFAULT,
  className,
  size = '100%',
}: MascotSVGProps) {
  const pose = FACE_POSE[face]
  const mouthPath = useMemo(() => buildMouthPath(viseme), [viseme])

  // Eye-blink uses pose.eyeScaleY; a periodic blink would be added at the
  // hook level (timing event), but the resting pose already varies enough
  // for now. Cheek dots use opacity for blush during 'speaking' / 'listening'.

  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 200 200"
      role="img"
      aria-label={`mascot ${face}`}
    >
      <defs>
        <radialGradient id="mascot-body-grad" cx="50%" cy="40%" r="70%">
          <stop offset="0%" stopColor={color} />
          <stop offset="100%" stopColor={SHADOW_COLOR} />
        </radialGradient>
        <filter id="mascot-soft-shadow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="2" />
        </filter>
      </defs>

      {/* Antennas — mirror Reachy Mini's physical antennas */}
      <g
        transform={`rotate(${pose.antennaAngle}, 75, 30)`}
        style={{ transition: animateAntennas ? 'transform 240ms ease-out' : undefined }}
      >
        <line x1="75" y1="30" x2="60" y2="6" stroke={SHADOW_COLOR} strokeWidth="3" strokeLinecap="round" />
        <circle cx="60" cy="6" r="6" fill={color} />
      </g>
      <g
        transform={`rotate(${-pose.antennaAngle}, 125, 30)`}
        style={{ transition: animateAntennas ? 'transform 240ms ease-out' : undefined }}
      >
        <line x1="125" y1="30" x2="140" y2="6" stroke={SHADOW_COLOR} strokeWidth="3" strokeLinecap="round" />
        <circle cx="140" cy="6" r="6" fill={color} />
      </g>

      {/* Body — yellow disc */}
      <g
        transform={`rotate(${pose.bodyTilt}, 100, 110)`}
        style={{ transition: 'transform 200ms ease-out' }}
      >
        <circle cx="100" cy="110" r="78" fill="url(#mascot-body-grad)" />

        {/* Cheeks */}
        <circle
          cx="55"
          cy="130"
          r="9"
          fill="#fb7185"
          opacity={pose.cheekOpacity}
          style={{ transition: 'opacity 240ms ease-out' }}
        />
        <circle
          cx="145"
          cy="130"
          r="9"
          fill="#fb7185"
          opacity={pose.cheekOpacity}
          style={{ transition: 'opacity 240ms ease-out' }}
        />

        {/* Eyes */}
        <g style={{ transition: 'transform 160ms ease-out' }}>
          <ellipse
            cx="74"
            cy="100"
            rx="11"
            ry={11 * pose.eyeScaleY}
            fill="#1f2937"
            style={{ transition: 'rx 160ms ease-out, ry 160ms ease-out' }}
          />
          <ellipse
            cx="126"
            cy="100"
            rx="11"
            ry={11 * pose.eyeScaleY}
            fill="#1f2937"
            style={{ transition: 'rx 160ms ease-out, ry 160ms ease-out' }}
          />
          {/* Eye highlights */}
          <circle cx="78" cy="96" r="3" fill="#fff" />
          <circle cx="130" cy="96" r="3" fill="#fff" />
        </g>

        {/* Brows */}
        <g
          transform={`rotate(${pose.browAngle}, 74, 82)`}
          style={{ transition: 'transform 200ms ease-out' }}
        >
          <line x1="64" y1="82" x2="84" y2="82" stroke={SHADOW_COLOR} strokeWidth="3" strokeLinecap="round" />
        </g>
        <g
          transform={`rotate(${-pose.browAngle}, 126, 82)`}
          style={{ transition: 'transform 200ms ease-out' }}
        >
          <line x1="116" y1="82" x2="136" y2="82" stroke={SHADOW_COLOR} strokeWidth="3" strokeLinecap="round" />
        </g>

        {/* Mouth */}
        <path
          d={mouthPath}
          fill="#1f2937"
          style={{ transition: 'd 60ms ease-out' }}
        />
      </g>
    </svg>
  )
}

// Re-export VISEMES for renderer probes.
export { VISEMES }
