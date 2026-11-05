$ErrorActionPreference='Stop'
$presentationRoot=(Resolve-Path -LiteralPath 'docs/발표').Path
$moveRecords=New-Object 'System.Collections.Generic.List[object]'
function Move-PresentationArtifact([string]$From,[string]$To){
 $source=(Resolve-Path -LiteralPath (Join-Path $presentationRoot $From)).Path
 $destination=[System.IO.Path]::GetFullPath((Join-Path $presentationRoot $To))
 $prefix=$presentationRoot.TrimEnd('\','/')+[System.IO.Path]::DirectorySeparatorChar
 if(-not $source.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or -not $destination.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){throw 'Move outside presentation folder blocked'}
 if(Test-Path -LiteralPath $destination){throw ('Destination exists: '+$destination)}
 $item=Get-Item -LiteralPath $source
 if($item.PSIsContainer){
  if($destination.StartsWith($source+[System.IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Cannot move directory inside itself'}
  $files=Get-ChildItem -LiteralPath $source -File -Recurse
  foreach($file in $files){$suffix=$file.FullName.Substring($source.Length).TrimStart('\','/');$newFile=Join-Path $destination $suffix;$moveRecords.Add(@{from=$file.FullName;to=$newFile;hash=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash;extension=$file.Extension})}
 }else{$moveRecords.Add(@{from=$source;to=$destination;hash=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash;extension=$item.Extension})}
 New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName($destination)) | Out-Null
 Move-Item -LiteralPath $source -Destination $destination
}
Move-PresentationArtifact 'Haven_프로젝트_계획서.pptx' 'archive/이전초안/Haven_프로젝트_계획서.pptx'
Move-PresentationArtifact 'Haven_프로젝트_계획서_초안.pptx' 'archive/이전초안/Haven_프로젝트_계획서_초안.pptx'
Move-PresentationArtifact 'Haven_통합계획_기반_프로젝트계획서_초안.pptx' 'archive/이전초안/Haven_통합계획_기반_프로젝트계획서_초안.pptx'
Move-PresentationArtifact 'Haven_통합계획_기반_미리보기.png' 'archive/이전초안/Haven_통합계획_기반_미리보기.png'
Move-PresentationArtifact 'Haven_계획서_내용미리보기.png' 'archive/이전초안/Haven_계획서_내용미리보기.png'
Move-PresentationArtifact 'Haven_계획서_표지.png' 'archive/이전초안/Haven_계획서_표지.png'
Move-PresentationArtifact '샘플_검토' 'archive/검토샘플'
Move-PresentationArtifact 'Haven_프로젝트_계획서_최종.pptx' 'Haven_프로젝트_계획서.pptx'
Move-PresentationArtifact 'Haven_프로젝트_계획서_발표대본.md' '발표대본.md'
Move-PresentationArtifact 'Haven_프로젝트_계획서_최종_미리보기.png' '미리보기/주요슬라이드.png'
Move-PresentationArtifact 'Haven_프로젝트_계획서_최종_전체미리보기.png' '미리보기/전체슬라이드.png'
Move-PresentationArtifact '통합계획_제작/build_haven_20261105.cjs' 'src/build_haven.cjs'
Move-PresentationArtifact '통합계획_제작/new-deck-manifest.json' 'src/manifest.json'
$oldSourceDirectory=Join-Path $presentationRoot '통합계획_제작'
if((Get-ChildItem -LiteralPath $oldSourceDirectory -Force | Measure-Object).Count -eq 0){Remove-Item -LiteralPath $oldSourceDirectory}
$moveRecords | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath 'tasks/presentation-organization/moves.json' -Encoding utf8
Write-Output ('Moved records: '+$moveRecords.Count)
