# Render saved workbook header metadata from verify_layer1.py; no changes to the XLSX.
Add-Type -AssemblyName System.Drawing
$projectRoot = Split-Path -Parent $PSScriptRoot
$reportDir = Join-Path $projectRoot 'outputs/layer1/reports'
$previewRows = Get-Content -LiteralPath (Join-Path $reportDir 'template_preview.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$previewIndex = 0
foreach ($sheet in $previewRows) {
    foreach ($offset in @(0, 8)) {
        $cells = @($sheet.cells | Select-Object -Skip $offset -First 8)
        $widths = @($cells | ForEach-Object { [int]($_.width * 7 + 5) })
        $totalWidth = ($widths | Measure-Object -Sum).Sum + 24
        $bitmap = New-Object System.Drawing.Bitmap([int]$totalWidth, 145)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.Clear([System.Drawing.Color]::White)
        $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
        $font = New-Object System.Drawing.Font('Calibri', 11, [System.Drawing.FontStyle]::Bold)
        $titleFont = New-Object System.Drawing.Font('Calibri', 12)
        $graphics.DrawString(($sheet.sheet + ' - columnas ' + ($offset + 1) + '-' + ($offset + 8)), $titleFont, [System.Drawing.Brushes]::Black, 12, 10)
        $x = 12
        for ($i = 0; $i -lt $cells.Count; $i++) {
            $cell = $cells[$i]
            $color = [System.Drawing.ColorTranslator]::FromHtml('#' + $cell.fill.Substring(2))
            $brush = New-Object System.Drawing.SolidBrush($color)
            $graphics.FillRectangle($brush, $x, 43, $widths[$i], 46)
            $rectangle = New-Object System.Drawing.RectangleF(($x + 5), 54, ($widths[$i] - 8), 34)
            $graphics.DrawString($cell.text, $font, [System.Drawing.Brushes]::White, $rectangle)
            $brush.Dispose()
            $x += $widths[$i]
        }
        $graphics.DrawString('Plantilla vacia: 0 filas de datos', $titleFont, [System.Drawing.Brushes]::DimGray, 12, 106)
        $bitmap.Save((Join-Path $reportDir ("template_preview_" + $previewIndex + ".png")), [System.Drawing.Imaging.ImageFormat]::Png)
        $previewIndex++
        $font.Dispose()
        $titleFont.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}
Write-Output 'Cuatro vistas de encabezados generadas desde el XLSX guardado.'

