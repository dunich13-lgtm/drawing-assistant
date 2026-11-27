# Massing model from data/massing.json (made by tools/massing_from_labels.py): every element is its
# 2D outline extruded from z = 0 to its labelled height. Re-runnable: rebuilds the 'DWG massing' group.
#   SuBridge.use('su_massing'); SuMassing.run            (or SuMassing.run('data/other.json'))
require 'json'
SuBridge.use('su_build_base')   # always reload: an older version may still be loaded in this SketchUp session

module SuMassing
  COLORS = [[214, 196, 168], [168, 190, 214], [190, 214, 168], [214, 168, 190], [200, 200, 200]]

  def self.run(file = 'data/massing.json')
    data = JSON.parse(File.read(File.join(SuBridge::ROOT, file), encoding: 'UTF-8'))
    lines = []
    report = SuBuild.run('DWG massing', 'DWG massing') do |b|
      data['elements'].each_with_index do |e, i|
        g = b.extrude(b.root.entities, e['outline'], 0.0, e['height'], tag: 'DWG massing',
                      mat: ["Massing #{e['id']}", COLORS[i % COLORS.size]], name: "#{e['id']} #{e['label']}")
        next unless g
        b.count(e['kind'] == 'circle' ? :cylinders : :blocks)
        bb = g.bounds
        lines << "#{e['id']} #{e['label']}: z #{bb.min.z.to_m.round(3)}..#{bb.max.z.to_m.round(3)} m, " \
                 "x #{bb.min.x.to_m.round(2)}..#{bb.max.x.to_m.round(2)}, y #{bb.min.y.to_m.round(2)}..#{bb.max.y.to_m.round(2)}"
      end
      (data['unlabelled_shapes'] || []).each { |s| b.note("no height label: #{s['kind']} on #{s['layer']} (#{s['footprint_m2']} m2)") }
      (data['labels_without_shape'] || []).each { |l| b.note("label outside any shape: #{l['text']}") }
    end
    ([report] + lines).join("\n")
  end
end
