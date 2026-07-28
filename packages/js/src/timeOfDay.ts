export function utcTimeOfDaySeconds(value: string): number {
  const match = /^(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|([+-])(\d{2}):(\d{2}))$/.exec(value)
  if (!match) throw new Error(`Invalid time-of-day constraint: ${value}`)

  const [, hoursString, minutesString, secondsString, fraction = '', timezone, sign, offsetHours = '00', offsetMinutes = '00'] = match
  const hours = Number(hoursString)
  const minutes = Number(minutesString)
  const seconds = Number(secondsString)
  const offset = (Number(offsetHours) * 60 + Number(offsetMinutes)) * 60
  if (hours > 23 || minutes > 59 || seconds > 59 || offsetHours > '23' || offsetMinutes > '59') {
    throw new Error(`Invalid time-of-day constraint: ${value}`)
  }

  const localSeconds = hours * 3_600 + minutes * 60 + seconds + Number(`0.${fraction}`)
  const signedOffset = timezone === 'Z' ? 0 : sign === '+' ? offset : -offset
  return (localSeconds - signedOffset + 86_400) % 86_400
}
