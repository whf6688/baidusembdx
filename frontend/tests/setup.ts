import '@testing-library/jest-dom/vitest'

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }),
})

Object.defineProperty(globalThis, 'NodeFilter', {
  value: window.NodeFilter || { SHOW_ELEMENT: 1, FILTER_ACCEPT: 1, FILTER_REJECT: 2, FILTER_SKIP: 3 },
  configurable: true,
})

class MutationObserverStub {
  observe() {}
  disconnect() {}
  takeRecords(): MutationRecord[] { return [] }
}
Object.defineProperty(globalThis, 'MutationObserver', { value: MutationObserverStub, configurable: true })
Object.defineProperty(window, 'MutationObserver', { value: MutationObserverStub, configurable: true })
