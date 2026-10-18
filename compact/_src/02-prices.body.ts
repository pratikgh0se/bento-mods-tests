// Statement 2: estimate label, pricesJson override, invalid JSON.

const CUSTOM = JSON.stringify({
  asOf: '2026-10-11',
  opus: { input: 10, output: 50, cacheRead: 1, write5m: 12.5, write1h: 20 },
})

t('C02 /coach prints the estimate label with the built-in table', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  const txt = await w.cmd('coach')
  expect(txt).toContain('estimate (prices as of 2026-10-11)')
  expect(txt).not.toContain(', custom)')
})

t('C02 pricesJson override ends ", custom)" and drives the figures', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  const txt = await w.cmd('coach')
  expect(txt).toContain('estimate (prices as of')
  expect(txt).toContain(', custom)')
  // 350k * 1.00 / 1e6 = $0.35 warm; 350k * 20 / 1e6 = $7.00 cold (write1h)
  const band = await w.band('terminal')
  expect(band).toContain('$0.35')
  expect(band).toContain('$7.00')
}, { options: { pricesJson: CUSTOM } })

t('C02 invalid pricesJson keeps the built-in table and throws nothing', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  const txt = await w.cmd('coach')
  expect(txt).toContain('estimate (prices as of 2026-10-11)')
  expect(txt).not.toContain(', custom)')
  expect(await w.band('terminal')).toContain('$0.07')
}, { options: { pricesJson: '{this is not json' } })
