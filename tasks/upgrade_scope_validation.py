# coding: utf-8
from pathlib import Path
p=Path('tasks/ppt-new-validation/render_new.ps1');s=p.read_text(encoding='utf-8-sig')
if '$cellFindings' not in s:
 anchor=' $result=@{slides=$pres.Slides.Count;render=$render;overflow=$findings}'
 assert anchor in s
 addition=''' $cellFindings=@();$cellCount=0
 foreach($slide in $pres.Slides){foreach($shape in $slide.Shapes){if($shape.HasTable -eq -1){for($r=1;$r -le $shape.Table.Rows.Count;$r++){for($c=1;$c -le $shape.Table.Columns.Count;$c++){$cell=$shape.Table.Cell($r,$c).Shape;$tf=$cell.TextFrame2;$cellCount++;if($tf.TextRange.BoundHeight -gt ($cell.Height-$tf.MarginTop-$tf.MarginBottom+2)){$cellFindings+=@{slide=$slide.SlideIndex;row=$r;column=$c;text=$tf.TextRange.Text}}}}}}}
 @{cells=$cellCount;overflow=$cellFindings}|ConvertTo-Json -Depth 5|Set-Content (Join-Path $workspace 'tasks/ppt-new-validation/table-validation.json') -Encoding utf8
 Write-Output ('Table cells: '+$cellCount+'; overflows: '+$cellFindings.Count)
'''
 s=s.replace(anchor,addition+anchor);p.write_text(s,encoding='utf-8')
