# Generic object builder (spec 002 R4 / NIN-10): data/<project>/build.json -> one root group "DWG objects <project>",
# one sub-group per view ("V15 План етаж 1  +0.00..+2.80"), every element extruded from base to top with its holes,
# tag + plain colour per layer. Re-runnable (rebuilds its root group), one undo step, aborts cleanly on any error.
#   SuBridge.use('su_objects'); SuObjects.run('venelin_r4')
#   SuObjects.verify('venelin_r4')     -> deviation of every built element from its drawing outline/levels
require 'json'
SuBridge.use('su_build_base')   # always reload: an older version may still be loaded in this SketchUp session

module SuObjects
  PALETTE = [[176, 176, 170], [214, 196, 168], [168, 190, 214], [190, 214, 168], [214, 168, 168],
             [200, 180, 220], [230, 210, 150], [150, 200, 200], [220, 170, 130], [160, 160, 200]]

  def self.data(project)
    JSON.parse(File.read(File.join(SuBridge::ROOT, 'data', project, 'build.json'), encoding: 'UTF-8'))
  end

  def self.root_name(project) "DWG objects #{project}" end

  def self.run(project)
    d = data(project)
    layers = d['elements'].map { |e| e['layer'] }.uniq.sort
    colour = layers.each_with_index.to_h { |l, i| [l, PALETTE[i % PALETTE.size]] }
    vtitle = d['views'].to_h { |v| [v['id'], v] }
    report = SuBuild.run(root_name(project)) do |b|
      groups = {}
      d['elements'].each do |e|
        vg = groups[e['view']] ||= begin
          v = vtitle[e['view']]
          g = b.root.entities.add_group
          g.name = format('%s %s  %+.2f..%+.2f', v['id'], v['title'][0, 40], v['base'], v['top'])
          g
        end
        g = b.extrude(vg.entities, e['outline'], e['base'], e['top'] - e['base'],
                      tag: "DWG #{e['layer']}", mat: ["DWG #{e['layer']}", colour[e['layer']]],
                      name: "#{e['id']} #{e['layer']}", holes: e['holes'])
        g ? b.count(:built) : b.count(:failed)
      end
      b.count(:views, groups.size)
      b.count(:excluded_in_data, d['excluded'].size)
    end
    report
  end

  # Every element: built bounding box vs the outline/levels it was built from. Reports the worst deviations (mm).
  def self.verify(project)
    d = data(project)
    want = d['elements'].to_h { |e| [e['id'], e] }
    root = Sketchup.active_model.entities.grep(Sketchup::Group).find { |g| g.name == root_name(project) }
    return 'root group not found' unless root
    seen, devs = 0, []
    root.entities.grep(Sketchup::Group).each do |vg|
      vg.entities.grep(Sketchup::Group).each do |g|
        id = g.name.split(' ').first
        e = want[id] or next
        seen += 1
        bb = Geom::BoundingBox.new
        c = g.definition.bounds
        tr = root.transformation * vg.transformation * g.transformation
        (0..7).each { |i| bb.add(c.corner(i).transform(tr)) }
        xs = e['outline'].map { |p| p[0] }; ys = e['outline'].map { |p| p[1] }
        dev = [bb.min.x.to_m - xs.min, bb.max.x.to_m - xs.max, bb.min.y.to_m - ys.min, bb.max.y.to_m - ys.max,
               bb.min.z.to_m - e['base'], bb.max.z.to_m - e['top']].map(&:abs).max
        devs << [dev, id]
      end
    end
    devs.sort!.reverse!
    within = devs.count { |dv, _| dv <= 0.01 }
    ["checked #{seen} of #{want.size} elements; within 1 cm: #{within}; max deviation #{(devs.first&.first.to_f * 1000).round(2)} mm",
     "worst: #{devs.first(5).map { |dv, id| "#{id} #{(dv * 1000).round(2)} mm" }.join(', ')}"].join("\n")
  end
end
