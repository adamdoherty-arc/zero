export function maskSensitive(value: string | null | undefined): string {
  if (!value) return ''
  if (value.length <= 4) return '****'
  return `${'*'.repeat(Math.max(0, value.length - 4))}${value.slice(-4)}`
}
