// Shared utility functions

export const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

export const formatDate = (date: Date | number): string => {
  const d = typeof date === 'number' ? new Date(date) : date
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

export const truncate = (str: string, length: number): string => {
  if (str.length <= length) return str
  return str.substring(0, length) + '...'
}

export const extractUrl = (text: string): string | null => {
  const urlRegex = /(https?:\/\/[^\s]+)/g
  const match = text.match(urlRegex)
  return match ? match[0] : null
}

export const isValidUrl = (text: string): boolean => {
  try {
    new URL(text)
    return true
  } catch {
    return false
  }
}

export const parseCommand = (command: string): { action: string; args: string[] } => {
  const parts = command.trim().split(/\s+/)
  return {
    action: parts[0] || '',
    args: parts.slice(1)
  }
}

export const debounce = <T extends (...args: any[]) => any>(
  func: T,
  wait: number
): ((...args: Parameters<T>) => void) => {
  let timeout: NodeJS.Timeout | null = null
  return (...args: Parameters<T>) => {
    if (timeout) clearTimeout(timeout)
    timeout = setTimeout(() => func(...args), wait)
  }
}

export const formatBytes = (bytes: number): string => {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
}

export const getFileExtension = (filename: string): string => {
  const parts = filename.split('.')
  return parts.length > 1 ? parts[parts.length - 1] : ''
}

export const isImageFile = (filename: string): boolean => {
  const ext = getFileExtension(filename).toLowerCase()
  return ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext)
}

export const isCodeFile = (filename: string): boolean => {
  const ext = getFileExtension(filename).toLowerCase()
  return ['js', 'ts', 'jsx', 'tsx', 'py', 'java', 'cpp', 'c', 'go', 'rs', 'rb'].includes(ext)
}