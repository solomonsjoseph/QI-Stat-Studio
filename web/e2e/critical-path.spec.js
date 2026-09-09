import { expect, test } from '@playwright/test'
import { writeFile } from 'node:fs/promises'

const e2eEnabled = process.env.QISS_E2E === '1'

async function answerClarificationQuestions(page, expectedAiTurnCount) {
  await page.locator('#q-1').fill('A fall-risk assessment protocol with intentional rounding.')
  await page.locator('#q-2').fill('The protocol began in January 2025.')
  await page.getByRole('button', { name: 'Submit Answers' }).click()
  await expect(page.getByText('AI Advisor', { exact: true })).toHaveCount(expectedAiTurnCount)
}

test.describe('critical resident workflow', () => {
  test.skip(!e2eEnabled, 'Set QISS_E2E=1 to run the live backend/frontend critical path.')

  test('resident completes the AI-guided workflow and creates a report share link', async ({ page }, testInfo) => {
    const email = `resident-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`
    const csvPath = testInfo.outputPath('monthly-falls.csv')
    await writeFile(
      csvPath,
      [
        'month,falls,patient_days',
        '2025-01-01,4,1000',
        '2025-02-01,3,1025',
        '2025-03-01,5,1010',
        '2025-04-01,2,1030',
        '2025-05-01,3,1045',
        '2025-06-01,2,1020',
        '2025-07-01,4,1050',
        '2025-08-01,3,1060',
        '2025-09-01,2,1040',
        '2025-10-01,3,1070',
        '2025-11-01,2,1055',
        '2025-12-01,1,1080',
      ].join('\n'),
    )

    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'QI Stat Studio' })).toBeVisible()

    await page.getByRole('tab', { name: 'Register' }).click()
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Password').fill('password123')
    await page.getByRole('button', { name: 'Create Account' }).click()

    await expect(page.getByRole('button', { name: 'Start New Project' })).toBeVisible()
    await page.getByRole('button', { name: 'Start New Project' }).click()

    await expect(page.getByRole('heading', { name: 'Tell us about your project.' })).toBeVisible()
    await expect(page.getByText('This prototype is not HIPAA compliant.')).toBeVisible()
    await page.getByLabel('Project Title').fill('Monthly inpatient falls')
    await page.getByLabel('Project Description').fill(
      'We are reducing inpatient falls through a fall-risk assessment and intentional rounding protocol.',
    )
    await page.getByLabel('CSV or Excel dataset').setInputFiles(csvPath)
    await page.getByRole('button', { name: 'Continue' }).click()

    await expect(page.getByRole('heading', { name: 'Project Clarification' })).toBeVisible()
    await expect(page.getByText('Tracking monthly inpatient falls normalized by patient days over time.')).toBeVisible()
    await expect(page.getByText('AI Advisor', { exact: true })).toHaveCount(1)

    // The stub asks the same two questions each turn. Four AI turns unlock the
    // resident-controlled confirmation path rather than relying on AI confirmation.
    await answerClarificationQuestions(page, 2)
    await answerClarificationQuestions(page, 3)
    await answerClarificationQuestions(page, 4)

    await expect(page.getByRole('button', { name: 'Confirm project definition →' })).toBeEnabled()
    await page.getByRole('button', { name: 'Confirm project definition →' }).click()

    await expect(page.getByRole('heading', { name: 'Data Review' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'What else you may need to collect' })).toBeVisible()
    await expect(page.getByText('Track fall severity or injury level')).toBeVisible()

    const warningCheckboxes = page.getByRole('checkbox')
    for (let index = 0; index < await warningCheckboxes.count(); index += 1) {
      await warningCheckboxes.nth(index).check()
    }
    await expect(page.getByRole('button', { name: 'Continue to Analysis Selection' })).toBeEnabled()
    await page.getByRole('button', { name: 'Continue to Analysis Selection' }).click()

    await expect(page.getByRole('heading', { name: 'Analysis Plan' })).toBeVisible()
    await expect(page.getByText('Summary of Monthly Counts and Patient Days')).toBeVisible()
    await expect(page.getByText('Monthly Fall Rate (U Chart)')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Continue' })).toBeEnabled()
    await page.getByRole('button', { name: 'Continue' }).click()

    await expect(page.getByRole('heading', { name: 'Final Confirmation' })).toBeVisible()
    await expect(page.getByText('value_cols')).toBeVisible()
    await expect(page.getByText('denominator_col')).toBeVisible()
    await page.getByRole('button', { name: 'Run these analyses' }).click()

    await expect(page.getByRole('heading', { name: 'Results' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'What the data show (descriptive)' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Descriptive Summary' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'u/c-Chart' })).toBeVisible()
    await page.getByRole('button', { name: 'Edit & Review' }).click()

    await expect(page.getByRole('heading', { name: 'Edit & Review' })).toBeVisible()
    await page.getByLabel('Report Title').fill('Resident-approved inpatient falls report')
    await page.getByLabel('Figure Caption').first().fill('Monthly inpatient falls and patient-day exposure.')
    await page.getByRole('button', { name: 'Save & Continue' }).click()

    await expect(page.getByRole('heading', { name: 'Download & Share' })).toBeVisible()
    await page.getByRole('button', { name: 'Generate report' }).click()
    await expect(page.getByRole('link', { name: 'Download Word (.docx)' })).toHaveAttribute(
      'href',
      /\/api\/report\/project\/\d+\/docx$/,
    )
    await expect(page.getByRole('link', { name: 'Download PDF' })).toHaveAttribute(
      'href',
      /\/api\/report\/project\/\d+\/pdf$/,
    )

    await page.getByLabel('Mentor Email (optional)').fill('mentor@example.edu')
    await page.getByRole('button', { name: 'Share with mentor' }).click()
    await expect(page.locator('code')).toHaveText(/\/mentor\//)
  })
})
