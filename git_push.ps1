param (
    [string]$Message = "Update app with recent changes"
)

Write-Host "Staging changes..." -ForegroundColor Cyan
git add .

Write-Host "Committing with message: '$Message'..." -ForegroundColor Cyan
git commit -m "$Message"

Write-Host "Pushing to repository..." -ForegroundColor Cyan
git push

Write-Host "Done!" -ForegroundColor Green