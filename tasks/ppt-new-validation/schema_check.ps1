$ErrorActionPreference='Stop'
$base='C:/Users/Minsoo/.agents/skills/synced/a43ab093-0be2-499a-ac28-68686dfc911c_9cc853e1-ee84-4bcc-b00e-ebb9bbb2bd3c/pptx/scripts/office/schemas/ISO-IEC29500-4_2016'
$schemas=New-Object System.Xml.Schema.XmlSchemaSet
$schemas.XmlResolver=New-Object System.Xml.XmlUrlResolver
[void]$schemas.Add('http://schemas.openxmlformats.org/presentationml/2006/main',(Join-Path $base 'pml.xsd'))
$schemas.Compile()
Write-Output ('Compiled XSD schema count: '+$schemas.Count)
$script:schemaIssues=New-Object 'System.Collections.Generic.List[string]'
$settings=New-Object System.Xml.XmlReaderSettings
$settings.ValidationType=[System.Xml.ValidationType]::Schema
$settings.Schemas=$schemas
$settings.DtdProcessing=[System.Xml.DtdProcessing]::Prohibit
$settings.XmlResolver=$null
$settings.add_ValidationEventHandler({param($sender,$eventArgs) $script:schemaIssues.Add($script:currentPart+' '+$eventArgs.Severity+' '+$eventArgs.Message)})
$deck=(Resolve-Path 'docs/발표/Haven_통합계획_기반_프로젝트계획서_초안.pptx').Path
$zip=[System.IO.Compression.ZipFile]::OpenRead($deck)
$count=0
try {
 foreach($entry in $zip.Entries){
  if($entry.FullName.StartsWith('ppt/') -and $entry.FullName.EndsWith('.xml')){
   $script:currentPart=$entry.FullName
   $stream=$entry.Open();$reader=$null
   try {$reader=[System.Xml.XmlReader]::Create($stream,$settings);while($reader.Read()){};$count++}finally{if($reader){$reader.Dispose()};$stream.Dispose()}
  }
 }
}finally{$zip.Dispose()}
$report=@{parts=$count;errors=$script:schemaIssues}
$report | ConvertTo-Json -Depth 5 | Set-Content tasks/ppt-new-validation/xsd-validation.json -Encoding utf8
Write-Output ('Validated XML parts: '+$count+'; XSD errors: '+$script:schemaIssues.Count)
$script:schemaIssues | Select-Object -First 12
