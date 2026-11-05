$ErrorActionPreference='Stop'
$workspace='C:/Users/Minsoo/Desktop/KT/projects/Haven'
$deck=Join-Path $workspace 'docs/발표/Haven_프로젝트_계획서_최종.pptx'
$render=Join-Path $workspace 'tasks/ppt-final-validation/render'
New-Item -ItemType Directory -Force -Path $render | Out-Null
$app=$null
$pres=$null
try {
 $app=New-Object -ComObject PowerPoint.Application
 $pres=$app.Presentations.Open($deck,$true,$false,$false)
 $pres.Export($render,'PNG',1600,900)
 $findings=@()
 foreach($slide in $pres.Slides){
  foreach($shape in $slide.Shapes){
   if($shape.HasTextFrame -eq -1 -and $shape.TextFrame.HasText -eq -1){
    $tf=$shape.TextFrame2
    $availableH=$shape.Height-$tf.MarginTop-$tf.MarginBottom
    $availableW=$shape.Width-$tf.MarginLeft-$tf.MarginRight
    if($tf.TextRange.BoundHeight -gt $availableH+2 -or $tf.TextRange.BoundWidth -gt $availableW+2){
     $findings+=@{slide=$slide.SlideIndex;shape=$shape.Name;text=$tf.TextRange.Text;boundH=$tf.TextRange.BoundHeight;availableH=$availableH;boundW=$tf.TextRange.BoundWidth;availableW=$availableW}
    }
   }
  }
 }
 $cellFindings=@();$cellCount=0
 foreach($slide in $pres.Slides){foreach($shape in $slide.Shapes){if($shape.HasTable -eq -1){for($r=1;$r -le $shape.Table.Rows.Count;$r++){for($c=1;$c -le $shape.Table.Columns.Count;$c++){$cell=$shape.Table.Cell($r,$c).Shape;$tf=$cell.TextFrame2;$cellCount++;if($tf.TextRange.BoundHeight -gt ($cell.Height-$tf.MarginTop-$tf.MarginBottom+2)){$cellFindings+=@{slide=$slide.SlideIndex;row=$r;column=$c;text=$tf.TextRange.Text}}}}}}}
 @{cells=$cellCount;overflow=$cellFindings}|ConvertTo-Json -Depth 5|Set-Content (Join-Path $workspace 'tasks/ppt-final-validation/table-validation.json') -Encoding utf8
 Write-Output ('Table cells: '+$cellCount+'; overflows: '+$cellFindings.Count)
 $result=@{slides=$pres.Slides.Count;render=$render;overflow=$findings}
 $result | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $workspace 'tasks/ppt-final-validation/powerpoint-validation.json') -Encoding utf8
 Write-Output ('PowerPoint rendered '+$pres.Slides.Count+' slides; text overflows: '+$findings.Count)
 foreach($f in $findings){Write-Output ('Slide '+$f.slide+' '+$f.shape+' '+$f.text.Replace("`r",' ').Substring(0,[Math]::Min(70,$f.text.Length)))}
} finally {
 if($pres){$pres.Close();[void][Runtime.InteropServices.Marshal]::ReleaseComObject($pres)}
 if($app){$app.Quit();[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
}
