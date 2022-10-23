from html_table_extractor.extractor import Extractor
class DirectorInformationTable:
    def __init__(self, html_content, orientation, director_surnames):
        extraction = Extractor(html_content)
        extraction.parse()
        extraction_list = extraction.return_list()
        self.initialize_cell_structure(extraction_list, orientation)
        uppercase_surnames = [x.upper() for x in director_surnames]
        self.find_header_where_the_directors_are(uppercase_surnames)
        self.find_director_column_numbers(uppercase_surnames)
        self.find_index_for_content()

    def initialize_cell_structure(self, extraction_list, orientation):
        self.cells = {}
        self.row_numbers = set()
        self.column_numbers = set()
        for x,c in enumerate(extraction_list):
            for y,d in enumerate(c):
                if orientation == 'row':
                    self.cells[(x,y)] = d
                    self.row_numbers.update([x])
                    self.column_numbers.update([y])
                else:
                    self.cells[(y,x)] = d
                    self.row_numbers.update([y])
                    self.column_numbers.update([x])

    def find_header_where_the_directors_are(self, uppercase_surnames):
        x_count = {}
        for name in uppercase_surnames:
            for cell in self.cells:
                if self.cells[cell] is None:
                    continue
                if name in self.cells[cell].upper():
                    x,y = cell
                    if x not in x_count:
                        x_count[x] = set()
                    x_count[x].update([name])
        best_score = 0
        self.header_idx = None
        for x in x_count:
            if len(x_count[x]) > best_score:
                best_score = len(x_count[x])
                self.header_idx = x
        if self.header_idx is None:
            # No director was found anywhere
            raise KeyError

    def find_director_column_numbers(self, uppercase_surnames):
        self.director_column_numbers = {}
        self.unused_columns = set(self.column_numbers)
        for y in self.column_numbers:
            if (self.header_idx,y) not in self.cells:
                continue
            data = self.cells[(self.header_idx,y)].upper()
            who = [name for name in uppercase_surnames if name in data]
            if len(who) > 1 or len(who) < 1:
                continue
            self.unused_columns.remove(y)
            who = who[0]
            if who in self.director_column_numbers:
                # Appears twice
                self.director_column_numbers[who] = None
                continue
            self.director_column_numbers[who] = y
        column_indexes = [x for x in self.director_column_numbers.values() if x is not None]
        if len(column_indexes) == 0:
            self.lowest_director_column_index = None
        else:
            self.lowest_director_column_index = min(column_indexes)

    def find_index_for_content(self):
        self.content_index_column = None
        diversity_score = 0
        if self.lowest_director_column_index is None:
            self.content_index = {}
            return
        for i in range(self.lowest_director_column_index):
            distinct_data = set()
            for x in self.row_numbers:
                distinct_data.update([self.cells.get((x,i),"")])
            if len(distinct_data) > diversity_score:
                self.content_index_column = i
                diversity_score = len(distinct_data)
        self.content_index = {}
        for x in self.row_numbers:
            self.content_index[x] = self.cells.get((x, self.content_index_column))

    def get_director_value_by_pos(self, director_surname, content_number):
        name = director_surname.upper()
        if name not in self.director_column_numbers:
            raise KeyError(name)
        return self.cells[(content_number, self.director_column_numbers[name])]

    def get_director_values(self, director_surname):
        answer = {}
        for content_number, content_name in self.content_index.items():
            try:
                answer[(content_number,content_name)] = self.get_director_value_by_pos(director_surname, content_number)
            except KeyError:
                pass
        return answer

    def get_values(self):
        return { director_surname : self.get_director_values(director_surname)
                 for director_surname in self.director_column_numbers }


    def get_range_diversity(self, start_row, end_row):
        if start_row > end_row:
            raise ValueError
        distinct_values = set([""])
        for row in range(start_row, end_row+1):
            for director in self.director_column_numbers:
                try:
                    distinct_values.update([self.get_director_value_by_pos(director, row)])
                except KeyError:
                    pass
        return distinct_values, len(distinct_values)-1

    def raw_regions_with_few_values(self, min_size=3):
        for r1 in self.row_numbers:
            for r2 in self.row_numbers:
                if r1 > r2:
                    continue
                if r1 + min_size > r2:
                    continue
                distinct_values, value_count = self.get_range_diversity(r1,r2)
                if value_count > 0 and value_count <= 2:
                    yield (r1,r2, [self.content_index[x] for x in range(r1,r2+1)], value_count, distinct_values)

    def regions_with_few_values(self, min_size=3):                    
        raw_answers= list(self.raw_regions_with_few_values(min_size))
        kill_list = set()
        for z1 in raw_answers:
            r1 = z1[0]
            r2 = z1[1]
            for z2 in raw_answers:
                q1 = z2[0]
                q2 = z2[1]
                if q1 == r1 and q2 == r2:
                    continue
                if q1 >= r1 and q2 <= r2:
                    # Then it is subsumed by the r1,r2
                    kill_list.update([(q1,q2)])
        for answer in raw_answers:
            r1 = answer[0]
            r2 = answer[1]
            if (r1,r2) in kill_list:
                continue
            yield answer

    def __getitem__(self, pos):
        return self.cells[pos]
    def __str__(self):
        return f"Row numbers = {sorted(list(self.row_numbers))}, Column numbers = {sorted(list(self.column_numbers))}\n{self.cells}\n\nHeader index = {self.header_idx}\nDirectors = {self.director_column_numbers}\nUnused columns={self.unused_columns}\nWill use column {self.content_index_column} as the index, giving indexes of {self.content_index}.\nSummarised by director: {self.get_values()}\n"

