import { expect, test } from '@playwright/test'
import { writeFile } from 'node:fs/promises'

// QISS_E2E=1 enables the live specs. QISS_E2E_MODE selects the backend this run targets:
//   stub  (default): backend started with AI_PROVIDER=stub
//   nokey: backend started with AI_PROVIDER=openrouter and no key (OPENROUTER_API_KEY empty)
const e2eEnabled = process.env.QISS_E2E === '1'
const mode = process.env.QISS_E2E_MODE || 'stub'

// 60 monthly rows. unit and ward carry whitespace padding and mixed case.
// staff_score is an integer column with 10% blanks and is not named like a denominator, so it must not be
// guessed as one; census_days is picked up as the denominator by its name.
// The review shows five warnings (the monthly dates are regular, so no date gap warning).
function buildCsv() {
  const units = ['ICU', ' icu', 'Med', 'med ', 'Surg']
  const wards = ['North', ' north', 'South', 'south ', 'East']
  const rows = ['month,falls,staff_score,census_days,unit,ward']
  for (let i = 0; i < 60; i += 1) {
    const month = String((i % 12) + 1).padStart(2, '0')
    const year = 2020 + Math.floor(i / 12)
    const score = i % 10 === 3 ? '' : String(2000 + ((i * 7) % 25))
    rows.push([`${year}-${month}-01`, (i * 7) % 4 + 2, score, 1000 + ((i * 13) % 60), units[i % 5], wards[i % 5]].join(','))
  }
  return rows.join('\n')
}

async function register(page) {
  const email = `handoff-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'QI Stat Studio' })).toBeVisible()
  await page.getByRole('tab', { name: 'Register' }).click()
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('password123')
  await page.getByRole('button', { name: 'Create Account' }).click()
}

async function createProjectAndUpload(page, testInfo, { withDictionary }) {
  const csvPath = testInfo.outputPath('unit-falls.csv')
  await writeFile(csvPath, buildCsv())
  await page.getByRole('button', { name: 'Start New Project' }).click()
  await expect(page.getByRole('heading', { name: 'Tell us about your project.' })).toBeVisible()
  await page.getByLabel('Project Title').fill('Unit level inpatient falls')
  await page.getByLabel('Project Description').fill(
    'We are reducing inpatient falls through a fall-risk assessment and intentional rounding protocol.',
  )
  await page.getByLabel('CSV or Excel dataset').setInputFiles(csvPath)
  if (withDictionary) {
    const dictPath = testInfo.outputPath('dictionary.txt')
    await writeFile(
      dictPath,
      'month: first day of the reporting month\nfalls: inpatient falls in the month\ncensus_days: patient days in the month\nunit: care unit\nward: hospital ward\nstaff_score: staffing score\n',
    )
    await page.getByLabel('Data dictionary file').setInputFiles(dictPath)
  }
  await page.getByRole('button', { name: 'Continue' }).click()
  // The first upload scan waits for the PHI model to load, which can take minutes.
  await expect(page.getByRole('heading', { name: 'Project Clarification' })).toBeVisible({ timeout: 240_000 })
}

async function answerClarificationQuestions(page, expectedAiTurnCount) {
  await page.locator('#q-1').fill('A fall-risk assessment protocol with intentional rounding.')
  await page.locator('#q-2').fill('The protocol began in January 2023.')
  await page.getByRole('button', { name: 'Submit Answers' }).click()
  await expect(page.getByText('QI Stat Advisor', { exact: true })).toHaveCount(expectedAiTurnCount)
}

async function planToResults(page) {
  await expect(page.getByRole('heading', { name: 'Analysis Plan' })).toBeVisible()
  // Low-confidence parameters must be reviewed before the plan can continue.
  const reviewed = page.getByRole('button', { name: "I've reviewed this" })
  await expect(page.getByText(/^(Ready|Needs your input)$/).first()).toBeVisible()
  while (await reviewed.count()) await reviewed.first().click()
  await expect(page.getByRole('button', { name: 'Continue' })).toBeEnabled()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'Final Confirmation' })).toBeVisible()
  await page.getByRole('button', { name: 'Run these analyses' }).click()
  await expect(page.getByRole('heading', { name: 'Results' })).toBeVisible()
}

function warningRow(page, text) {
  return page.getByRole('listitem').filter({ hasText: text })
}

test.describe('handoff and warning review', () => {
  test.skip(!e2eEnabled, 'Set QISS_E2E=1 to run the live backend/frontend flows.')
  test.setTimeout(360_000)

  test('AI mode: acknowledge some warnings, clarify the rest with the QI Stat Advisor', async ({ page }, testInfo) => {
    test.skip(mode !== 'stub', 'Needs a backend started with AI_PROVIDER=stub (QISS_E2E_MODE=stub).')
    await register(page)
    await createProjectAndUpload(page, testInfo, { withDictionary: true })

    // Stub clarification: four AI turns unlock the resident confirmation button.
    await expect(page.getByText('QI Stat Advisor', { exact: true })).toHaveCount(1)
    await answerClarificationQuestions(page, 2)
    await answerClarificationQuestions(page, 3)
    await answerClarificationQuestions(page, 4)
    await page.getByRole('button', { name: 'Confirm project definition →' }).click()

    await expect(page.getByRole('heading', { name: 'Data Review' })).toBeVisible()
    await expect(page.getByText('60 rows')).toBeVisible()
    await expect(page.getByText(/Tick the warnings you want to handle, then choose Acknowledge or Clarify with the QI Stat Advisor/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Continue to Analysis Selection' })).toBeDisabled()

    // staff_score has blanks and is not named like a denominator, so it is not guessed as one.
    // census_days is picked up by its name: one denominator, no conflict note.
    await expect(page.getByLabel('Role for census_days')).toHaveValue('denominator')
    await expect(page.getByLabel('Role for staff_score')).not.toHaveValue('denominator')
    await expect(page.getByRole('status').filter({ hasText: /columns are set as Denominator/ })).toHaveCount(0)

    // Round one: acknowledge two warnings.
    await warningRow(page, 'staff_score').getByRole('checkbox').check()
    await warningRow(page, "Mixed case in 'ward'").getByRole('checkbox').check()
    await expect(page.getByText('2 selected')).toBeVisible()
    await page.getByRole('button', { name: 'Acknowledge selected' }).click()
    await expect(page.getByText('0 selected')).toBeVisible()
    await expect(warningRow(page, 'staff_score').getByText('(Handled)')).toBeVisible()
    await expect(warningRow(page, "Mixed case in 'ward'").getByText('(Handled)')).toBeVisible()

    // Round two: clarify the remaining warnings.
    const rows = page.getByRole('listitem').filter({ has: page.getByRole('checkbox') })
    const openBoxes = rows.getByRole('checkbox').and(page.locator(':not(:disabled)'))
    const remaining = await openBoxes.count()
    expect(remaining).toBe(3)
    for (let i = 0; i < remaining; i += 1) await openBoxes.nth(i).check()
    await expect(page.getByText(`${remaining} selected`)).toBeVisible()
    await page.getByRole('button', { name: 'Clarify with QI Stat Advisor' }).click()

    const chat = page.getByRole('region', { name: 'QI Stat Advisor' })
    await expect(chat).toBeVisible()
    const log = chat.getByRole('log')
    await expect(log.getByText('Here is what I would do for each selected warning')).toBeVisible()
    // The advisor spoke first: the opening trigger is not shown as a user turn.
    await expect(log.getByText('You', { exact: true })).toHaveCount(0)

    await chat.getByLabel('Your reply to the QI Stat Advisor').fill('Yes, please apply those changes.')
    await chat.getByRole('button', { name: 'Send' }).click()
    await expect(log.getByText('You', { exact: true })).toHaveCount(1)
    await expect(chat.getByText(/Proposed changes: read-back/)).toBeVisible()
    await expect(chat.getByText(/\(\d+ rows affected\)/).first()).toBeVisible()

    await chat.getByRole('button', { name: 'Confirm these changes' }).click()
    await expect(chat.getByText(/Applied as revision/)).toBeVisible()
    await expect(page.getByText('(Handled)')).toHaveCount(5)
    await chat.getByRole('button', { name: 'Close chat' }).click()

    // Handoff document: one example shown, the rest collapsed.
    await page.getByRole('button', { name: 'View handoff document' }).click()
    const doc = page.getByRole('region', { name: 'Handoff document' })
    await expect(doc).toBeVisible()
    await expect(doc.getByText(/^Example: /).first()).toBeVisible()
    const more = doc.locator('details').first()
    await expect(more).toBeVisible()
    await expect(more.locator('summary')).toHaveText(/Show \d+ more examples?/)
    expect(await more.evaluate(el => el.open)).toBe(false)
    await expect(doc.getByText(/Examples:/)).toHaveCount(0)
    await page.getByRole('button', { name: 'Hide handoff document' }).click()

    await expect(page.getByRole('button', { name: 'Continue to Analysis Selection' })).toBeEnabled()
    await page.getByRole('button', { name: 'Continue to Analysis Selection' }).click()

    await planToResults(page)
    await expect(page.getByText(/must contain only positive values/)).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'QI Stat Advisor interpretation' }).first()).toBeVisible()
    await expect(page.getByText('The QI Stat Advisor is off. You can write your own')).toHaveCount(0)
    const body = await page.locator('body').innerText()
    expect(body).not.toMatch(/AI advisor/i)
  })

  test('No-AI mode: manual design, acknowledge-only review, interpretation off, key from Settings', async ({ page }, testInfo) => {
    test.skip(mode !== 'nokey', 'Needs a backend started with AI_PROVIDER=openrouter and no key (QISS_E2E_MODE=nokey).')
    await register(page)

    await expect(page.getByRole('heading', { name: 'The QI Stat Advisor needs an AI key' })).toBeVisible()
    await page.getByRole('button', { name: 'Continue without the QI Stat Advisor' }).click()

    await createProjectAndUpload(page, testInfo, { withDictionary: false })

    // No chat: the manual design form replaces it.
    await expect(page.getByText('The QI Stat Advisor is off, so there is no conversation.')).toBeVisible()
    await expect(page.locator('#q-1')).toHaveCount(0)
    await page.getByLabel('Primary outcome column').selectOption('falls')
    await page.getByLabel('Date column').selectOption('month')
    await page.getByLabel('Time granularity').selectOption('month')
    await page.getByRole('button', { name: /Save and continue to Data Review/ }).click()

    await expect(page.getByRole('heading', { name: 'Data Review' })).toBeVisible()
    await expect(page.getByText('The QI Stat Advisor is not available. You can still acknowledge warnings.')).toBeVisible()
    // census_days is guessed as the denominator by its name; staff_score (blanks) is not.
    await expect(page.getByLabel('Role for census_days')).toHaveValue('denominator')
    await page.getByRole('checkbox', { name: 'Select all' }).check()
    await expect(page.getByRole('button', { name: 'Clarify with QI Stat Advisor' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Acknowledge selected' })).toBeEnabled()
    await expect(page.getByRole('button', { name: 'Continue to Analysis Selection' })).toBeDisabled()

    await page.getByRole('button', { name: 'Acknowledge selected' }).click()
    await expect(page.getByText('(Not handled)')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Continue to Analysis Selection' })).toBeEnabled()
    await page.getByRole('button', { name: 'Continue to Analysis Selection' }).click()

    await planToResults(page)
    await expect(page.getByText('The QI Stat Advisor is off. You can write your own')).toBeVisible()

    // Settings: a typed key is reported by source and last four characters only.
    await page.getByRole('button', { name: 'Open settings' }).click()
    await expect(page.getByText('No key set. The QI Stat Advisor is off.')).toBeVisible()
    await page.getByLabel('New key').fill('sk-or-fake-test-key-9z4Q')
    await page.getByRole('button', { name: 'Save key' }).click()
    await expect(page.getByText('Key set from Settings, ending in 9z4Q.')).toBeVisible()
    await expect(page.getByText('sk-or-fake-test-key')).toHaveCount(0)
    await expect(page.getByLabel('New key')).toHaveValue('')

    // A second registered user is not an admin. Settings must open without an error alert and show the AI key section.
    await page.getByRole('button', { name: 'Sign out' }).click()
    await register(page)
    // The admin's saved key is shared, so the second user may or may not see the key prompt.
    const skip = page.getByRole('button', { name: 'Continue without the QI Stat Advisor' })
    await expect(skip.or(page.getByRole('button', { name: 'Start New Project' }))).toBeVisible()
    if (await skip.count()) await skip.click()
    await page.getByRole('button', { name: 'Open settings' }).click()
    await expect(page.getByRole('heading', { name: 'AI key' })).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
  })
})
