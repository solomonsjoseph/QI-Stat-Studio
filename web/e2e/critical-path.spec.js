import { expect, test } from '@playwright/test'
import { writeFile } from 'node:fs/promises'

const e2eEnabled = process.env.QISS_E2E === '1'

test.describe('critical resident workflow', () => {
  test.skip(!e2eEnabled, 'Set QISS_E2E=1 to run the live backend/frontend critical path.')

  test('resident completes analysis, creates mentor share, and mentor comments', async ({ page }, testInfo) => {
    const email = `resident-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`
    const csvPath = testInfo.outputPath('resident-run-chart.csv')
    await writeFile(
      csvPath,
      [
        'month,wait_days',
        '2025-01-01,12',
        '2025-02-01,11',
        '2025-03-01,10',
        '2025-04-01,9',
        '2025-05-01,8',
        '2025-06-01,7',
        '2025-07-01,7',
        '2025-08-01,6',
        '2025-09-01,6',
        '2025-10-01,5',
        '2025-11-01,5',
        '2025-12-01,4',
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

    await expect(page.getByRole('heading', { name: 'Describe Your QI Project' })).toBeVisible()
    await page.getByLabel('Project Title').fill('Resident run chart project')
    await page.getByLabel('Project Description').fill('Track monthly median wait days after a scheduling improvement.')
    await page.getByRole('button', { name: 'Continue' }).click()

    await expect(page.getByRole('heading', { name: 'Intake Questions' })).toBeVisible()
    await page.getByLabel('An average or median value (average LDL)').check()
    await page.getByRole('button', { name: /Next/ }).click()

    await page.getByLabel("No — I'm just describing one time period").check()
    await page.getByRole('button', { name: /Next/ }).click()

    await page.getByLabel('Tracking over time (months, weeks, days)').check()
    await page.getByRole('button', { name: /Next/ }).click()

    await page.getByLabel('Monthly').check()
    await page.getByRole('button', { name: /Next/ }).click()

    await page.getByRole('spinbutton', { name: 'How many time points (or rows) do you have?' }).fill('12')
    await page.getByRole('button', { name: /Next/ }).click()

    await page.getByLabel('R', { exact: true }).check()
    await page.getByRole('button', { name: /Next/ }).click()

    await page.getByLabel('Submission deadline').fill('2026-10-15')
    await page.getByRole('button', { name: 'Continue' }).click()

    await expect(page.getByRole('heading', { name: 'Upload Your Data' })).toBeVisible()
    await page.getByLabel('CSV or Excel file').setInputFiles(csvPath)
    await page.getByRole('button', { name: 'Upload CSV/Excel' }).click()

    await expect(page.getByRole('heading', { name: 'Confirm Column Types' })).toBeVisible()
    await page.getByLabel('Type for month').selectOption('Date')
    await page.getByLabel('Type for wait_days').selectOption('Number')
    await page.getByRole('button', { name: /Confirm Types/ }).click()

    await expect(page.getByRole('heading', { name: 'Data Review' })).toBeVisible()
    for (const checkbox of await page.getByRole('checkbox').all()) {
      await checkbox.check()
    }
    await page.getByRole('button', { name: 'Continue to Analysis Selection' }).click()

    await expect(page.getByRole('heading', { name: 'Choose Your Analysis' })).toBeVisible()
    await page.getByRole('button', { name: /Run Chart/ }).click()
    await page.getByRole('button', { name: 'Continue' }).click()

    await expect(page.getByRole('heading', { name: 'Map Your Columns' })).toBeVisible()
    await page.getByLabel('Date column').selectOption('month')
    await page.getByLabel('Value column').selectOption('wait_days')
    await page.getByRole('button', { name: 'Run Analysis' }).click()

    await expect(page.getByRole('heading', { name: 'Results' })).toBeVisible()
    await expect(page.getByAltText('Analysis figure')).toBeVisible()
    await expect(page.getByRole('button', { name: /Edit & Review|Preparing interpretation/ })).toBeEnabled()
    await page.getByRole('button', { name: /Edit & Review|Preparing interpretation/ }).click()

    await expect(page.getByRole('heading', { name: 'Edit & Review' })).toBeVisible()
    await page.getByLabel('Report Title').fill('Resident-approved run chart report')
    await page.getByLabel('Figure Caption').fill('Monthly wait days declined over the project year.')
    await page.getByLabel('Interpretation').fill('Wait days declined after the scheduling workflow stabilized.')
    await page.getByRole('button', { name: 'Save & Continue' }).click()

    await expect(page.getByRole('heading', { name: 'Download & Share' })).toBeVisible()
    await page.getByRole('button', { name: 'Generate report' }).click()
    await expect(page.getByRole('link', { name: 'Download Word (.docx)' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Download PDF' })).toBeVisible()
    await page.getByRole('button', { name: 'Share with mentor' }).click()
    const shareLink = await page.locator('code').innerText()
    expect(shareLink).toContain('/mentor/')

    await page.goto(shareLink)
    await expect(page.getByRole('heading', { name: 'Mentor Comments' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Resident-approved run chart report' })).toBeVisible()
    await expect(page.getByText('Monthly wait days declined over the project year.')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Download Word Report' })).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Download PDF Report' })).toHaveCount(0)

    await page.getByLabel('Your name').fill('Dr Mentor')
    await page.getByLabel('Email (optional, used if you edit your comment later)').fill('mentor@example.edu')
    await page.getByLabel('Comment', { exact: true }).fill('Looks ready to share with faculty.')
    await page.getByRole('button', { name: 'Send Comment' }).click()

    await expect(page.getByText('Comment submitted.')).toBeVisible()
    await expect(page.getByText('Looks ready to share with faculty.')).toBeVisible()
  })
})
